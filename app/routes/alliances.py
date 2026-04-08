from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_socketio import emit, join_room, leave_room
from app.models import AllianceSelection, Team, Event, Match, ScoutingData, DoNotPickEntry, AvoidEntry, db, team_event, DeclinedEntry, WantListEntry, TeamTagEntry
from app.utils.analysis import calculate_team_metrics, get_epa_metrics_for_team
from app.utils.statbotics_api_utils import get_statbotics_team_matches
from flask_login import current_user
from app import socketio
from sqlalchemy import func, desc, and_
import json
import re
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_current_game_config, get_effective_game_config
from app.utils.alliance_data import (
    get_all_teams_for_alliance,
    get_scouting_data_for_team,
    get_all_qualitative_data,
    get_all_pit_data,
)
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_events_by_scouting_team,
    filter_alliance_selections_by_scouting_team, filter_do_not_pick_by_scouting_team,
    filter_avoid_entries_by_scouting_team, assign_scouting_team_to_model,
    get_current_scouting_team_number, get_event_by_code, resolve_event_id_from_param,
    get_all_teams_at_event, filter_scouting_data_by_scouting_team, resolve_event_from_param
)
from app.utils.team_isolation import filter_declined_entries_by_scouting_team, get_combined_dropdown_events, filter_want_list_by_scouting_team

bp = Blueprint('alliances', __name__, url_prefix='/alliances')

PICK_META_PREFIX = '__PICKMETA__:'
TEAM_TAG_META_PREFIX = '__TEAMTAG__:'


def _decode_pick_meta(reason):
    parsed = {
        'note': '',
        'offense_tag': False,
        'defense_tag': False
    }
    if not reason:
        return parsed

    if isinstance(reason, str) and reason.startswith(PICK_META_PREFIX):
        raw_json = reason[len(PICK_META_PREFIX):]
        try:
            payload = json.loads(raw_json)
            parsed['note'] = str(payload.get('note', '') or '')[:120]
            parsed['offense_tag'] = bool(payload.get('offense_tag', False))
            parsed['defense_tag'] = bool(payload.get('defense_tag', False))
            return parsed
        except Exception:
            pass

    parsed['note'] = str(reason)[:120]
    return parsed


def _encode_pick_meta(note, offense_tag=False, defense_tag=False):
    clean_note = (note or '').strip()[:120]
    payload = {
        'note': clean_note,
        'offense_tag': bool(offense_tag),
        'defense_tag': bool(defense_tag)
    }
    return PICK_META_PREFIX + json.dumps(payload, separators=(',', ':'))


def _decode_team_tag_meta(reason):
    parsed = {
        'note': '',
        'custom_tags': [],
        # Legacy fields for backward compatibility
        'offense_tag': False,
        'defense_tag': False
    }
    if not reason:
        return parsed

    if isinstance(reason, str) and reason.startswith(TEAM_TAG_META_PREFIX):
        raw_json = reason[len(TEAM_TAG_META_PREFIX):]
        try:
            payload = json.loads(raw_json)
            parsed['note'] = str(payload.get('note', '') or '')[:120]
            # Support new custom_tags format
            if 'custom_tags' in payload:
                parsed['custom_tags'] = payload.get('custom_tags', [])
                if isinstance(parsed['custom_tags'], str):
                    parsed['custom_tags'] = [t.strip() for t in parsed['custom_tags'].split() if t.strip()]
                else:
                    parsed['custom_tags'] = [str(t).strip() for t in (parsed['custom_tags'] or [])]
            # Legacy support for offense/defense tags
            parsed['offense_tag'] = bool(payload.get('offense_tag', False))
            parsed['defense_tag'] = bool(payload.get('defense_tag', False))
            return parsed
        except Exception:
            pass

    parsed['note'] = str(reason)[:120]
    return parsed


def _encode_team_tag_meta(note, custom_tags=None, offense_tag=False, defense_tag=False):
    clean_note = (note or '').strip()[:120]
    # Convert custom_tags to list if needed
    tags_list = []
    if custom_tags:
        if isinstance(custom_tags, str):
            tags_list = [t.strip() for t in custom_tags.split() if t.strip()]
        elif isinstance(custom_tags, list):
            tags_list = [str(t).strip() for t in custom_tags]
    
    payload = {
        'note': clean_note,
        'custom_tags': tags_list,
        # Keep legacy fields for backward compatibility
        'offense_tag': bool(offense_tag),
        'defense_tag': bool(defense_tag)
    }
    return TEAM_TAG_META_PREFIX + json.dumps(payload, separators=(',', ':'))

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

# SocketIO event handlers for real-time sync
@socketio.on('join_alliance_room')
def on_join_alliance_room(data):
    """Join a room for alliance updates"""
    event_id = data.get('event_id')
    if event_id:
        join_room(f'alliance_event_{event_id}')
        emit('status', {'msg': f'Joined alliance room for event {event_id}'})

@socketio.on('leave_alliance_room')
def on_leave_alliance_room(data):
    """Leave a room for alliance updates"""
    event_id = data.get('event_id')
    if event_id:
        leave_room(f'alliance_event_{event_id}')
        emit('status', {'msg': f'Left alliance room for event {event_id}'})

def emit_alliance_update(event_id, alliance_data):
    """Emit alliance update to all clients in the room"""
    socketio.emit('alliance_updated', alliance_data, room=f'alliance_event_{event_id}')

def emit_recommendations_update(event_id):
    """Emit recommendations update to all clients in the room"""
    socketio.emit('recommendations_updated', {'event_id': event_id}, room=f'alliance_event_{event_id}')

def emit_lists_update(event_id, list_data):
    """Emit lists update to all clients in the room"""
    socketio.emit('lists_updated', list_data, room=f'alliance_event_{event_id}')

@bp.route('/')
def index():
    """Alliance selection main page"""
    # Get all events for dropdown (combined + deduped as /events)
    events = get_combined_dropdown_events()
    selected_event_param = request.args.get('event')
    current_event = None
    current_event_id = None

    # Prefer an explicit event selection from the page querystring. This keeps
    # selection local to /alliances and avoids mutating global/current config.
    if selected_event_param:
        current_event = resolve_event_from_param(selected_event_param, events=events)
        current_event_id = resolve_event_id_from_param(selected_event_param, events=events)
        # For synthetic alliance events that don't resolve to a local Event row,
        # keep the synthetic id so client requests stay pinned to the selected event.
        if current_event_id is None and current_event is not None:
            current_event_id = getattr(current_event, 'id', None)
    
    # If no explicit event selected, use effective config event and then fall back.
    if not current_event:
        game_config = get_effective_game_config()
        current_event_code = game_config.get('current_event_code')

        if current_event_code:
            # Use get_event_by_code which handles year-prefixed codes
            current_event = get_event_by_code(current_event_code)
        else:
            # Prefer a real Event object (with numeric id) as the fallback current event
            if events:
                # Prefer first ORM Event (numeric id), fall back to first entry regardless
                current_event = next((e for e in events if isinstance(getattr(e, 'id', None), int)), events[0])
    
    if not current_event:
        flash('No events found. Please create an event first.', 'warning')
        return redirect(url_for('main.index'))

    # Resolve the concrete numeric event id for DB operations. Synthetic alliance-type
    # event objects may use ids like 'alliance_2026OKOK' which cannot be compared
    # directly against integer foreign keys.
    if current_event_id is None:
        if isinstance(getattr(current_event, 'id', None), int):
            current_event_id = current_event.id
        else:
            current_event_id = resolve_event_id_from_param(getattr(current_event, 'code', None), events=events)

    if current_event_id is None:
        flash('Could not resolve the selected event to a valid event record.', 'danger')
        return redirect(url_for('main.index'))

    # Get existing alliances for the current event (filtered by scouting team)
    # Fetch ordered by alliance_number and newest timestamp first so the first row for a
    # given alliance_number is the canonical one.
    raw_alliances = []
    if isinstance(current_event_id, int):
        raw_alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == current_event_id
        ).order_by(AllianceSelection.alliance_number, AllianceSelection.timestamp.desc()).all()

    # Deduplicate by alliance_number, keeping the latest (by timestamp). Collect duplicates
    # for removal so the database remains clean and the UI doesn't show repeated alliance cards.
    alliances_by_num = {}
    duplicates = []
    for a in raw_alliances:
        num = a.alliance_number
        if num not in alliances_by_num:
            alliances_by_num[num] = a
        else:
            duplicates.append(a)

    if duplicates:
        current_app.logger.info(f"Removing {len(duplicates)} duplicate alliance rows for event {current_event_id}")
        for dup in duplicates:
            db.session.delete(dup)
        db.session.commit()

    # Build final alliances list ordered by alliance_number
    alliances = [alliances_by_num[n] for n in sorted(alliances_by_num.keys())]

    # Create 8 alliances if they don't exist
    if isinstance(current_event_id, int) and len(alliances) < 8:
        for i in range(1, 9):
            existing = next((a for a in alliances if a.alliance_number == i), None)
            if not existing:
                    new_alliance = AllianceSelection(alliance_number=i, event_id=current_event_id)
                    assign_scouting_team_to_model(new_alliance)  # Assign current scouting team
                    db.session.add(new_alliance)
        db.session.commit()
        alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == current_event_id
        ).order_by(AllianceSelection.alliance_number).all()

    return render_template('alliances/index.html',
                         alliances=alliances,
                         current_event=current_event,
                         current_event_id=current_event_id,
                         events=events,
                         **get_theme_context())

@bp.route('/recommendations/<event_param>')
def get_recommendations(event_param):
    """Get team recommendations based on points scored"""
    try:
        event_id = resolve_event_id_from_param(event_param)
        if event_id is None:
            try:
                if str(event_param).strip().isdigit():
                    event_id = int(str(event_param).strip())
            except Exception:
                event_id = None

        # Check whether client requested trend-aware ranking (default true)
        use_trends = request.args.get('use_trends', '1') not in ('0', 'false', 'False')
        event = None
        if event_id is not None:
            event = Event.query.get(event_id)

        event_code = ''
        if event and getattr(event, 'code', None):
            event_code = (event.code or '').upper()
        else:
            raw_param = str(event_param or '').strip()
            if raw_param.startswith('alliance_'):
                event_code = raw_param[len('alliance_'):].strip().upper()
            elif raw_param and not raw_param.isdigit():
                event_code = raw_param.upper()
            if not event_code:
                try:
                    cfg_code = (get_effective_game_config().get('current_event_code') or '').strip().upper()
                    event_code = cfg_code
                except Exception:
                    event_code = ''

        scoped_event_ids = []
        if event_code:
            event_code_variants = [event_code]
            if len(event_code) > 4 and event_code[:4].isdigit():
                event_code_variants.append(event_code[4:])
            try:
                scoped_event_ids = [
                    row[0] for row in filter_events_by_scouting_team()
                    .with_entities(Event.id)
                    .filter(func.upper(Event.code).in_(event_code_variants))
                    .all()
                ]
            except Exception:
                scoped_event_ids = []
            if not scoped_event_ids:
                scoped_event_ids = [
                    row[0] for row in Event.query.with_entities(Event.id)
                    .filter(func.upper(Event.code).in_(event_code_variants))
                    .all()
                ]

        if event_id is not None and event_id not in scoped_event_ids:
            scoped_event_ids.append(event_id)
        if not scoped_event_ids and not event_code:
            return jsonify({'error': 'Event not found'}), 404
        
        # Prefer alliance-aware team loading first. In alliance mode this uses event-code
        # scoping across member datasets and avoids going empty when only one member has
        # populated team_event links.
        all_teams = []
        try:
            alliance_teams, is_alliance_mode = get_all_teams_for_alliance(
                event_id=event_id,
                event_code=event_code
            )
            if is_alliance_mode and alliance_teams:
                all_teams = alliance_teams
        except Exception:
            all_teams = []

        # Fallback to direct event association query (normal mode and non-alliance cases).
        if not all_teams and scoped_event_ids:
            all_teams = filter_teams_by_scouting_team().join(
                Team.events
            ).filter(
                Event.id.in_(scoped_event_ids)
            ).order_by(Team.team_number).all()
        
        # Deduplicate teams in case of duplicate rows from join operations.
        # Use team_number as the dedupe key so two different DB rows representing the
        # same real team (same team_number) are not shown twice when server IDs differ.
        seen_team_numbers = set()
        unique_all_teams = []
        for t in all_teams:
            if not t:
                continue
            team_num = getattr(t, 'team_number', None)
            # Fall back to id if team_number is absent for some reason
            key = team_num if team_num is not None else getattr(t, 'id', None)
            if key not in seen_team_numbers:
                seen_team_numbers.add(key)
                unique_all_teams.append(t)
        if len(unique_all_teams) != len(all_teams):
            current_app.logger.info(f"Deduplicated teams for event {event_id}: {len(all_teams)} -> {len(unique_all_teams)}")
        all_teams = unique_all_teams

        # If no teams found in team_event, broaden to event-code-aware team discovery.
        if not all_teams:
            all_teams = get_all_teams_at_event(event_id=event_id, event_code=event_code)

        # Final fallback: derive teams from scouting rows visible to this user/alliance
        # for any event row that shares the selected code.
        if not all_teams and scoped_event_ids:
            from app.models import Match
            scoped_team_ids = [
                row[0] for row in filter_scouting_data_by_scouting_team(
                    db.session.query(ScoutingData.team_id).join(Match, ScoutingData.match_id == Match.id)
                ).filter(
                    Match.event_id.in_(scoped_event_ids)
                ).distinct().all()
            ]
            if scoped_team_ids:
                all_teams = filter_teams_by_scouting_team().filter(
                    Team.id.in_(scoped_team_ids)
                ).order_by(Team.team_number).all()

        # Last-resort fallback: derive team numbers directly from match alliances
        # for the selected event scope. This avoids blank recommendations when
        # team_event links are missing or stale in alliance mode.
        if not all_teams and scoped_event_ids:
            from app.models import Match

            def _extract_team_numbers(raw_alliance):
                if not raw_alliance:
                    return []
                if isinstance(raw_alliance, (list, tuple)):
                    values = raw_alliance
                else:
                    values = [raw_alliance]
                nums = []
                for value in values:
                    try:
                        nums.extend(int(x) for x in re.findall(r'\d+', str(value)))
                    except Exception:
                        continue
                return nums

            match_rows = Match.query.filter(Match.event_id.in_(scoped_event_ids)).all()
            match_team_numbers = set()
            for m in match_rows:
                match_team_numbers.update(_extract_team_numbers(getattr(m, 'red_alliance', None)))
                match_team_numbers.update(_extract_team_numbers(getattr(m, 'blue_alliance', None)))

            if match_team_numbers:
                all_teams = filter_teams_by_scouting_team().filter(
                    Team.team_number.in_(match_team_numbers)
                ).order_by(Team.team_number).all()

        if not all_teams:
            current_app.logger.warning(
                "No teams resolved for alliance recommendations: event_param=%s event_id=%s event_code=%s scoped_event_ids=%s",
                event_param,
                event_id,
                event_code,
                scoped_event_ids,
            )
        
        # Get game configuration
        game_config = get_effective_game_config()
        
        # Find metric IDs from game config
        component_metric_ids = []
        total_metric_id = None
        metric_info = {}
        
        # Identify metrics from game config
        if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
            for metric in game_config['data_analysis']['key_metrics']:
                metric_id = metric.get('id')
                metric_info[metric_id] = {
                    'name': metric.get('name'),
                    'is_component': metric.get('is_total_component', False)
                }
                
                # Check if this is a component metric or the total metric
                if metric.get('is_total_component'):
                    component_metric_ids.append(metric_id)
                elif 'total' in metric_id.lower() or 'tot' == metric_id.lower():
                    total_metric_id = metric_id
        
        # If no component metrics defined, use default IDs
        if not component_metric_ids:
            component_metric_ids = ["apt", "tpt", "ept"]
        
        # If no total metric defined, use default ID
        if not total_metric_id:
            total_metric_id = "tot"
            
        # Get teams already picked in alliances (filtered by scouting team)
        picked_teams = set()
        picked_team_numbers = set()
        if isinstance(event_id, int):
            alliances = filter_alliance_selections_by_scouting_team().filter(
                AllianceSelection.event_id == event_id
            ).all()
            for alliance in alliances:
                picked_teams.update(alliance.get_all_teams())

            if picked_teams:
                picked_team_numbers = set(
                    row[0] for row in Team.query.with_entities(Team.team_number).filter(
                        Team.id.in_(picked_teams)
                    ).all() if row and row[0] is not None
                )
        
        # Get avoid and do not pick lists for this event (filtered by scouting team)
        avoid_teams = set()
        do_not_pick_teams = set()
        avoid_team_numbers = set()
        do_not_pick_team_numbers = set()
        if isinstance(event_id, int):
            avoid_entries = filter_avoid_entries_by_scouting_team().filter(
                AvoidEntry.event_id == event_id
            ).all()
            do_not_pick_entries = filter_do_not_pick_by_scouting_team().filter(
                DoNotPickEntry.event_id == event_id
            ).all()

            avoid_teams = set(entry.team_id for entry in avoid_entries)
            do_not_pick_teams = set(entry.team_id for entry in do_not_pick_entries)
            avoid_team_numbers = set(
                row[0] for row in Team.query.with_entities(Team.team_number).filter(
                    Team.id.in_(avoid_teams)
                ).all() if row and row[0] is not None
            )
            do_not_pick_team_numbers = set(
                row[0] for row in Team.query.with_entities(Team.team_number).filter(
                    Team.id.in_(do_not_pick_teams)
                ).all() if row and row[0] is not None
            )

        # Get declined list for this event (filtered by scouting team)
        declined_teams = set()
        declined_team_numbers = set()
        if isinstance(event_id, int):
            declined_teams = set(entry.team_id for entry in filter_declined_entries_by_scouting_team().filter(
                DeclinedEntry.event_id == event_id
            ).all())
            declined_team_numbers = set(
                row[0] for row in Team.query.with_entities(Team.team_number).filter(
                    Team.id.in_(declined_teams)
                ).all() if row and row[0] is not None
            )
        
        # Get want list for this event (filtered by scouting team) with rankings
        want_list_entries = []
        if isinstance(event_id, int):
            want_list_entries = filter_want_list_by_scouting_team().filter(
                WantListEntry.event_id == event_id
            ).all()
        want_list_teams = {}  # Map team_number to rank
        want_list_tags = {}  # Legacy fallback: tags previously stored on want list entries (by team_number)
        want_team_ids = [entry.team_id for entry in want_list_entries if entry.team_id]
        want_team_num_by_id = {}
        if want_team_ids:
            want_team_num_by_id = {
                row[0]: row[1] for row in Team.query.with_entities(Team.id, Team.team_number).filter(
                    Team.id.in_(want_team_ids)
                ).all() if row and row[1] is not None
            }
        for entry in want_list_entries:
            team_num = want_team_num_by_id.get(entry.team_id)
            if team_num is None:
                continue
            want_list_teams[team_num] = entry.rank
            meta = _decode_pick_meta(entry.reason)
            want_list_tags[team_num] = {
                'offense_tag': meta['offense_tag'],
                'defense_tag': meta['defense_tag'],
                'pick_note': meta['note']
            }

        # Separate Team Tags list (preferred source for offense/defense tag sorting)
        team_tag_entries = []
        if isinstance(event_id, int):
            team_tag_entries = TeamTagEntry.query.filter_by(
                event_id=event_id,
                scouting_team_number=current_user.scouting_team_number
            ).all()
        team_tag_team_ids = [entry.team_id for entry in team_tag_entries if entry.team_id]
        team_tag_num_by_id = {}
        if team_tag_team_ids:
            team_tag_num_by_id = {
                row[0]: row[1] for row in Team.query.with_entities(Team.id, Team.team_number).filter(
                    Team.id.in_(team_tag_team_ids)
                ).all() if row and row[1] is not None
            }
        team_tags = {}
        for entry in team_tag_entries:
            team_num = team_tag_num_by_id.get(entry.team_id)
            if team_num is None:
                continue
            meta = _decode_team_tag_meta(entry.reason)
            team_tags[team_num] = {
                'custom_tags': meta.get('custom_tags', []),
                'offense_tag': meta['offense_tag'],
                'defense_tag': meta['defense_tag'],
                'pick_note': meta['note']
            }
        
        # Calculate metrics for available teams
        team_recommendations = []
        do_not_pick_recommendations = []  # Separate list for do not pick teams
        teams_with_no_data = []  # For teams without scouting data
        
        for team in all_teams:
            team_key = team.team_number if getattr(team, 'team_number', None) is not None else team.id
            is_picked = (team.id in picked_teams) or (team_key in picked_team_numbers)
            if not is_picked:
                tag_meta = team_tags.get(team_key, want_list_tags.get(team_key, {
                    'custom_tags': [],
                    'offense_tag': False,
                    'defense_tag': False,
                    'pick_note': ''
                }))
                try:
                    analytics_result = calculate_team_metrics(team.id)
                    metrics = analytics_result.get('metrics', {})
                    if metrics:
                        is_avoided = (team.id in avoid_teams) or (team_key in avoid_team_numbers)
                        is_dnp = (team.id in do_not_pick_teams) or (team_key in do_not_pick_team_numbers)
                        is_want = team_key in want_list_teams
                        is_declined = (team.id in declined_teams) or (team_key in declined_team_numbers)
                        team_data = {
                            'team': team,
                            'metrics': metrics,
                            'total_points': metrics.get('total_points', 0),
                            'auto_points': metrics.get('auto_points', 0),
                            'teleop_points': metrics.get('teleop_points', 0),
                            'endgame_points': metrics.get('endgame_points', 0),
                            'is_avoided': is_avoided,
                            'is_do_not_pick': is_dnp,
                            'is_want_list': is_want,
                            'want_list_rank': want_list_teams.get(team_key, 999),
                            'custom_tags': tag_meta.get('custom_tags', []),
                            'offense_tag': tag_meta.get('offense_tag', False),
                            'defense_tag': tag_meta.get('defense_tag', False),
                            'pick_note': tag_meta.get('pick_note', '')
                        
                        }
                        
                        # Mark declined flag for client to decide visibility
                        team_data['is_declined'] = is_declined

                        if is_dnp:
                            do_not_pick_recommendations.append(team_data)
                        else:
                            team_recommendations.append(team_data)
                    else:
                        is_avoided = (team.id in avoid_teams) or (team_key in avoid_team_numbers)
                        is_dnp = (team.id in do_not_pick_teams) or (team_key in do_not_pick_team_numbers)
                        is_want = team_key in want_list_teams
                        is_declined = (team.id in declined_teams) or (team_key in declined_team_numbers)
                        # Team exists but has no metrics data
                        teams_with_no_data.append({
                            'team': team,
                            'metrics': {},
                            'total_points': 0,
                            'auto_points': 0,
                            'teleop_points': 0,
                            'endgame_points': 0,
                            'is_avoided': is_avoided,
                            'is_do_not_pick': is_dnp,
                            'is_declined': is_declined,
                            'has_no_data': True,
                            'is_want_list': is_want,
                            'want_list_rank': want_list_teams.get(team_key, 999),
                            'custom_tags': tag_meta.get('custom_tags', []),
                            'offense_tag': tag_meta.get('offense_tag', False),
                            'defense_tag': tag_meta.get('defense_tag', False),
                            'pick_note': tag_meta.get('pick_note', '')
                        })
                except Exception as e:
                    print(f"Error calculating metrics for team {team.team_number}: {e}")
                    is_avoided = (team.id in avoid_teams) or (team_key in avoid_team_numbers)
                    is_dnp = (team.id in do_not_pick_teams) or (team_key in do_not_pick_team_numbers)
                    is_want = team_key in want_list_teams
                    is_declined = (team.id in declined_teams) or (team_key in declined_team_numbers)
                    # Still add the team without metrics
                    teams_with_no_data.append({
                        'team': team,
                        'metrics': {},
                        'total_points': 0,
                        'auto_points': 0,
                        'teleop_points': 0,
                        'endgame_points': 0,
                        'is_avoided': is_avoided,
                        'is_do_not_pick': is_dnp,
                        'is_declined': is_declined,
                        'has_no_data': True,
                        'is_want_list': is_want,
                        'want_list_rank': want_list_teams.get(team_key, 999),
                        'custom_tags': tag_meta.get('custom_tags', []),
                        'offense_tag': tag_meta.get('offense_tag', False),
                        'defense_tag': tag_meta.get('defense_tag', False),
                        'pick_note': tag_meta.get('pick_note', '')
                    })
        
        # Optionally apply a small trend adjustment to the sort key.
        # If two teams are very close in average points, prefer the one trending up.
        def _compute_recent_trend(team_obj, event_filter=None, max_history=12):
            """Compute a trend slope (points per match) for a team by combining slopes from
            multiple historical windows. This avoids overreacting to a single last-match
            value and captures both recent form and longer-term trends.

            Approach:
              - Collect up to `max_history` recent records (by timestamp).
              - Compute simple linear slope on multiple windows (recent, mid, long).
              - Combine slopes with weights favoring recent data but including longer history.

            Returns combined slope (float).
            """
            try:
                from app.models import Match
                # Fetch recent records ordered by timestamp ascending so x indexes map to time
                q = ScoutingData.query.filter(ScoutingData.team_id == team_obj.id)
                if event_filter:
                    q = q.join(Match).filter(Match.event_id == event_filter)
                records = q.order_by(ScoutingData.timestamp).all()
                if not records:
                    return 0.0

                # Limit to most recent max_history entries
                records = records[-max_history:]
                n = len(records)
                if n < 2:
                    return 0.0

                # Helper: compute slope for a list of numeric y values (x is implicit indices)
                def _slope_from_ys(ys):
                    m = len(ys)
                    if m < 2:
                        return 0.0
                    xs = list(range(m))
                    mean_x = sum(xs) / m
                    mean_y = sum(ys) / m
                    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, ys))
                    den = sum((xi - mean_x) ** 2 for xi in xs) or 1.0
                    return num / den

                # Build total points timeline
                totals = []
                for rec in records:
                    try:
                        auto_pts = rec._calculate_auto_points_dynamic(rec.data, game_config)
                        teleop_pts = rec._calculate_teleop_points_dynamic(rec.data, game_config)
                        endgame_pts = rec._calculate_endgame_points_dynamic(rec.data, game_config)
                        total_pts = auto_pts + teleop_pts + endgame_pts
                    except Exception:
                        total_pts = 0.0
                        if isinstance(rec.data, dict):
                            for v in rec.data.values():
                                if isinstance(v, (int, float)):
                                    total_pts += v
                    totals.append(float(total_pts))

                # Define windows: recent (last 3-5), mid (last ~8), long (up to max_history)
                recent_w = min(5, n)
                mid_w = min(8, n)
                long_w = n

                recent_slope = _slope_from_ys(totals[-recent_w:]) if recent_w >= 2 else 0.0
                mid_slope = _slope_from_ys(totals[-mid_w:]) if mid_w >= 2 else 0.0
                long_slope = _slope_from_ys(totals[-long_w:]) if long_w >= 2 else 0.0

                # Weighted combination (favor recent but include longer-term): Tunable weights
                combined = (0.6 * recent_slope) + (0.3 * mid_slope) + (0.1 * long_slope)

                return combined
            except Exception:
                return 0.0

        # Sort regular teams by total points (descending), but adjust by a small trend factor when use_trends is True
        def get_sort_key(team_data):
            base_score = team_data['total_points']
            # Avoid penalty for avoided teams at this stage (handled separately by badge)
            trend_adj = 0.0
            if use_trends:
                try:
                    team_obj = team if False else Team.query.get(team_data['team'].id if isinstance(team_data.get('team'), Team) else team_data['team_id'])
                except Exception:
                    team_obj = None
                # NB: team_obj may be None when team_data originates from teams_with_no_data path
                if team_obj:
                    try:
                        # Use a longer history for stability
                        slope = _compute_recent_trend(team_obj, event_filter=event_id, max_history=12)
                        # Convert slope (points per match) to a score adjustment. Use a modest weight
                        # and cap to avoid extreme influence from noisy data.
                        trend_adj = max(min(slope * 1.0, 8.0), -8.0)  # cap adjustment to +/-8 points
                    except Exception:
                        trend_adj = 0.0

            effective = base_score + trend_adj
            
            # Apply want list boost - higher priority (lower rank number) gets larger boost
            # Rank 1 gets biggest boost, rank 2 slightly less, etc.
            if team_data.get('is_want_list', False):
                rank = team_data.get('want_list_rank', 999)
                # Calculate boost: rank 1 = +50 points, rank 2 = +40, rank 3 = +30, etc.
                # Use formula: max(60 - (rank * 10), 5) to give diminishing boosts
                want_boost = max(60 - (rank * 10), 5)
                effective += want_boost
            
            # Penalize avoided teams slightly
            if team_data['is_avoided']:
                return effective * 0.7  # Reduce score by 30% for avoided teams
            return effective

        team_recommendations.sort(key=get_sort_key, reverse=True)
        
        # Sort do not pick teams separately
        do_not_pick_recommendations.sort(key=lambda x: x['total_points'], reverse=True)
        
        # Sort teams with no data by team number
        teams_with_no_data.sort(key=lambda x: x['team'].team_number)
        
        # Combine lists: regular teams first, then do not pick teams, then teams with no data
        all_recommendations = team_recommendations + do_not_pick_recommendations + teams_with_no_data
        
        # Build the recommendations list
        result_recommendations = []
        for rec in all_recommendations:
            # Build component metrics display string
            component_display_parts = []
            def _resolve_metric(metrics_dict, metric_id):
                """Resolve a metric value from metrics_dict using common aliases and case-insensitive matches."""
                if not metrics_dict:
                    return 0
                # Direct match
                if metric_id in metrics_dict:
                    return metrics_dict.get(metric_id) or 0

                # Common aliases
                alias_map = {
                    'apt': 'auto_points',
                    'tpt': 'teleop_points',
                    'ept': 'endgame_points',
                    'auto': 'auto_points',
                    'teleop': 'teleop_points',
                    'endgame': 'endgame_points',
                    'tot': 'total_points'
                }
                low = metric_id.lower()
                if low in alias_map and alias_map[low] in metrics_dict:
                    return metrics_dict.get(alias_map[low]) or 0

                # Try case-insensitive key match and substring matches
                for k, v in metrics_dict.items():
                    if not k:
                        continue
                    if k.lower() == low:
                        return v or 0
                for k, v in metrics_dict.items():
                    if low in k.lower() or k.lower() in low:
                        return v or 0

                # Last resort: if metric_id looks like a short code (1-4 chars), try mapping by known prefixes
                if low.startswith('a') and 'auto_points' in metrics_dict:
                    return metrics_dict.get('auto_points') or 0
                if low.startswith('t') and 'teleop_points' in metrics_dict:
                    return metrics_dict.get('teleop_points') or 0
                if low.startswith('e') and 'endgame_points' in metrics_dict:
                    return metrics_dict.get('endgame_points') or 0

                return 0

            for i, metric_id in enumerate(component_metric_ids):
                if i == 0:
                    prefix = "A:"  # Auto
                elif i == 1:
                    prefix = "T:"  # Teleop
                elif i == 2:
                    prefix = "E:"  # Endgame
                else:
                    # Use first letter of metric name for other components
                    metric_name = metric_info.get(metric_id, {}).get('name', metric_id)
                    prefix = f"{metric_name[0]}:"

                raw_val = _resolve_metric(rec.get('metrics', {}), metric_id)
                try:
                    value = round(float(raw_val), 1)
                except Exception:
                    value = 0

                component_display_parts.append(f"{prefix}{value}")

            component_metrics_display = " ".join(component_display_parts)

            # Determine total points robustly: prefer configured total_metric_id, then 'total_points', then sum components
            metrics_dict = rec.get('metrics', {}) or {}
            total_val = 0
            if total_metric_id and total_metric_id in metrics_dict:
                total_val = metrics_dict.get(total_metric_id, 0) or 0
            elif 'total_points' in metrics_dict:
                total_val = metrics_dict.get('total_points', 0) or 0
            else:
                # Sum component metrics if available
                for mid in component_metric_ids:
                    mval = metrics_dict.get(mid, 0) or 0
                    try:
                        total_val += float(mval)
                    except Exception:
                        continue

            team_data = {
                'team_id': rec['team'].id,
                'team_number': rec['team'].team_number,
                'team_name': rec['team'].team_name or f"Team {rec['team'].team_number}",
                'total_points': round(total_val, 1),
                'component_metrics_display': component_metrics_display,
                # Keep these for backwards compatibility
                'auto_points': round(metrics_dict.get(component_metric_ids[0], metrics_dict.get('auto_points', 0)) or 0, 1) if component_metric_ids else 0,
                'teleop_points': round(metrics_dict.get(component_metric_ids[1], metrics_dict.get('teleop_points', 0)) or 0, 1) if len(component_metric_ids) > 1 else 0,
                'endgame_points': round(metrics_dict.get(component_metric_ids[2], metrics_dict.get('endgame_points', 0)) or 0, 1) if len(component_metric_ids) > 2 else 0,
                'is_avoided': rec['is_avoided'],
                'is_do_not_pick': rec['is_do_not_pick'],
                'is_declined': rec.get('is_declined', False),
                'has_no_data': rec.get('has_no_data', False),
                'is_want_list': rec.get('is_want_list', False),
                'want_list_rank': rec.get('want_list_rank', 999),
                'custom_tags': rec.get('custom_tags', []),
                'offense_tag': rec.get('offense_tag', False),
                'defense_tag': rec.get('defense_tag', False),
                'pick_note': rec.get('pick_note', '')
            }
            # Compute recent trend (slope) for client display (small, robust indicator)
            try:
                slope = _compute_recent_trend(rec['team'], event_filter=event_id, max_history=12)
            except Exception:
                slope = 0.0

            # Small threshold to avoid noisy up/down flips
            THRESHOLD = 0.05
            if slope > THRESHOLD:
                direction = 'up'
            elif slope < -THRESHOLD:
                direction = 'down'
            else:
                direction = 'flat'

            team_data['trend_slope'] = round(float(slope), 2)
            team_data['trend_direction'] = direction
            # Predict next match score using average total_points plus recent slope
            try:
                predicted = float(team_data.get('total_points', 0)) + float(slope)
            except Exception:
                predicted = float(team_data.get('total_points', 0))
            team_data['predicted_points'] = round(predicted, 1)
            result_recommendations.append(team_data)
        
        return jsonify({
            'recommendations': result_recommendations
        })
        
    except Exception as e:
        print(f"Error in get_recommendations: {e}")
        return jsonify({'error': str(e), 'recommendations': []}), 500

@bp.route('/api/update', methods=['POST'])
def update_alliance():
    """Update alliance selection via API"""
    data = request.get_json()
    
    alliance_id = data.get('alliance_id')
    position = data.get('position')
    team_id = data.get('team_id')
    
    if not all([alliance_id, position, team_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Validate position
    if position not in ['captain', 'first_pick', 'second_pick', 'third_pick']:
        return jsonify({'success': False, 'message': 'Invalid position'})
    
    # Get the alliance
    alliance = AllianceSelection.query.filter_by(id=alliance_id, scouting_team_number=current_user.scouting_team_number).first()
    alliance = AllianceSelection.query.filter_by(id=alliance_id, scouting_team_number=current_user.scouting_team_number).first()
    if not alliance:
        return jsonify({'success': False, 'message': 'Alliance not found'})
    
    # Get the team
    team = filter_teams_by_scouting_team().filter_by(team_number=team_id).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})
    
    # Check if team is already picked in any alliance for this event
    existing_alliances = AllianceSelection.query.filter_by(event_id=alliance.event_id).all()
    for existing_alliance in existing_alliances:
        if team.id in existing_alliance.get_all_teams():
            return jsonify({
                'success': False, 
                'message': f'Team {team_id} is already selected in Alliance {existing_alliance.alliance_number}'
            })
    
    # Update the alliance
    setattr(alliance, position, team.id)
    
    try:
        db.session.commit()
        
        # Emit real-time update with complete data
        alliance_data = {
            'alliance_id': alliance.id,
            'alliance_number': alliance.alliance_number,
            'position': position,
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'action': 'assign'
        }
        emit_alliance_update(alliance.event_id, alliance_data)
        emit_recommendations_update(alliance.event_id)
        
        return jsonify({'success': True, 'message': f'Team {team_id} assigned to Alliance {alliance.alliance_number}'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@bp.route('/api/remove', methods=['POST'])
def remove_team():
    """Remove a team from alliance selection"""
    data = request.get_json()
    
    alliance_id = data.get('alliance_id')
    position = data.get('position')
    
    if not all([alliance_id, position]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Validate position
    if position not in ['captain', 'first_pick', 'second_pick', 'third_pick']:
        return jsonify({'success': False, 'message': 'Invalid position'})
    
    # Get the alliance
    alliance = AllianceSelection.query.get(alliance_id)
    if not alliance:
        return jsonify({'success': False, 'message': 'Alliance not found'})
    
    # Remove the team
    setattr(alliance, position, None)
    
    try:
        db.session.commit()
        
        # Emit real-time update
        alliance_data = {
            'alliance_id': alliance.id,
            'alliance_number': alliance.alliance_number,
            'position': position,
            'team_id': None,
            'team_number': None,
            'team_name': None,
            'action': 'remove'
        }
        emit_alliance_update(alliance.event_id, alliance_data)
        emit_recommendations_update(alliance.event_id)
        
        return jsonify({'success': True, 'message': 'Team removed from alliance'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

@bp.route('/reset/<event_param>')
def reset_alliances(event_param):
    """Reset all alliance selections for an event"""
    event_id = resolve_event_id_from_param(event_param)
    if event_id is None:
        flash('Could not reset alliances: selected event is not mapped to a local event record yet.', 'warning')
        return redirect(url_for('alliances.index', event=event_param))

    event = Event.query.get_or_404(event_id)
    
    # Clear all alliance selections for this event
    alliances = AllianceSelection.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).all()
    for alliance in alliances:
        alliance.captain = None
        alliance.first_pick = None
        alliance.second_pick = None
        alliance.third_pick = None
    
    try:
        db.session.commit()
        
        # Emit real-time reset update
        socketio.emit('alliances_reset', {'event_id': event_id}, room=f'alliance_event_{event_id}')
        emit_recommendations_update(event_id)
        
        flash('Alliance selections have been reset.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error resetting alliances: {str(e)}', 'danger')
    
    return redirect(url_for('alliances.index'))

@bp.route('/manage_lists/<event_param>')
def manage_lists(event_param):
    """Manage avoid, do not pick, declined, custom pick, and team tag lists"""
    event_id = resolve_event_id_from_param(event_param)
    if event_id is None:
        flash('Could not open manage lists: selected event is not mapped to a local event record yet.', 'warning')
        return redirect(url_for('alliances.index', event=event_param))

    event = Event.query.get_or_404(event_id)
    
    # Get current lists
    avoid_entries = AvoidEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).all()
    do_not_pick_entries = DoNotPickEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).all()
    declined_entries = DeclinedEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).all()
    want_list_entries = filter_want_list_by_scouting_team().filter_by(event_id=event_id).join(Team).order_by(WantListEntry.rank).all()
    team_tag_entries = TeamTagEntry.query.filter_by(event_id=event_id, scouting_team_number=current_user.scouting_team_number).join(Team).order_by(Team.team_number).all()
    want_list_display_entries = []
    for entry in want_list_entries:
        meta = _decode_pick_meta(entry.reason)
        want_list_display_entries.append({
            'team_id': entry.team_id,
            'team': entry.team,
            'rank': entry.rank,
            'note': meta['note']
        })
    team_tag_display_entries = []
    for entry in team_tag_entries:
        meta = _decode_team_tag_meta(entry.reason)
        team_tag_display_entries.append({
            'team_id': entry.team_id,
            'team': entry.team,
            'note': meta['note'],
            'custom_tags': meta.get('custom_tags', []),
            'offense_tag': meta['offense_tag'],
            'defense_tag': meta['defense_tag']
        })
    
    # Get all teams for this event from team_event relationship
    all_teams = db.session.query(Team).join(
        team_event, Team.id == team_event.c.team_id
    ).filter(
        team_event.c.event_id == event_id
    ).order_by(Team.team_number).all()

    # If no teams found in team_event relationship, fall back to all teams with scouting data
    if not all_teams:
        from app.models import Match
        all_teams = db.session.query(Team).join(ScoutingData).join(
            Match, ScoutingData.match_id == Match.id
        ).filter(
            Match.event_id == event_id
        ).distinct().order_by(Team.team_number).all()

    # Deduplicate teams in case the join returns multiple identical rows for the same team
    # (e.g., duplicate team_event entries). Keep the first occurrence (teams are ordered by team_number).
    seen_numbers = set()
    deduped_teams = []
    for t in all_teams:
        if t.team_number not in seen_numbers:
            seen_numbers.add(t.team_number)
            deduped_teams.append(t)
    if len(deduped_teams) != len(all_teams):
        current_app.logger.info(f"Deduplicated {len(all_teams) - len(deduped_teams)} team rows for event {event_id} on manage_lists page")
    all_teams = deduped_teams
    
    return render_template('alliances/manage_lists.html',
                         event=event,
                         avoid_entries=avoid_entries,
                         do_not_pick_entries=do_not_pick_entries,
                         declined_entries=declined_entries,
                         want_list_entries=want_list_entries,
                         want_list_display_entries=want_list_display_entries,
                         team_tag_display_entries=team_tag_display_entries,
                         all_teams=all_teams,
                         **get_theme_context())

@bp.route('/api/add_to_list', methods=['POST'])
def add_to_list():
    """Add a team to avoid or do not pick list"""
    data = request.get_json()
    
    team_number = data.get('team_number')
    event_id = data.get('event_id')
    list_type = data.get('list_type')  # 'avoid' or 'do_not_pick'
    reason = data.get('reason', '')
    
    if not all([team_number, event_id, list_type]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    if list_type not in ['avoid', 'do_not_pick', 'declined']:
        return jsonify({'success': False, 'message': 'Invalid list type'})
    
    # Get the team
    team = filter_teams_by_scouting_team().filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})
    
    # Check if team is already in the list
    if list_type == 'avoid':
        existing = AvoidEntry.query.filter_by(team_id=team.id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
        if existing:
            return jsonify({'success': False, 'message': 'Team already in avoid list'})
        
        entry = AvoidEntry(team_id=team.id, event_id=event_id, reason=reason, scouting_team_number=current_user.scouting_team_number)
    else:  # do_not_pick or declined
        if list_type == 'do_not_pick':
            existing = DoNotPickEntry.query.filter_by(team_id=team.id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
            if existing:
                return jsonify({'success': False, 'message': 'Team already in do not pick list'})
            entry = DoNotPickEntry(team_id=team.id, event_id=event_id, reason=reason, scouting_team_number=current_user.scouting_team_number)
        else:  # declined
            existing = DeclinedEntry.query.filter_by(team_id=team.id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
            if existing:
                return jsonify({'success': False, 'message': 'Team already in declined list'})
            entry = DeclinedEntry(team_id=team.id, event_id=event_id, reason=reason, scouting_team_number=current_user.scouting_team_number)
    
    try:
        db.session.add(entry)
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': list_type,
            'reason': reason,
            'action': 'add'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': f'Team {team_number} added to {list_type.replace("_", " ")} list'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/get_alliances/<event_param>')
def get_alliances(event_param):
    """Get current state of all alliances for an event"""
    try:
        event_id = resolve_event_id_from_param(event_param)
        if event_id is None:
            if str(event_param or '').strip().startswith('alliance_'):
                return jsonify({'success': True, 'alliances': []})
            return jsonify({'success': False, 'error': 'Event not found or not accessible'}), 404

        # Fetch ordered by alliance_number and newest timestamp so the first seen row is the canonical one
        raw_alliances = filter_alliance_selections_by_scouting_team().filter(
            AllianceSelection.event_id == event_id
        ).order_by(AllianceSelection.alliance_number, AllianceSelection.timestamp.desc()).all()

        # Keep one alliance row per alliance_number (the latest). Do NOT modify DB here; just return a
        # de-duplicated view for the client. Log any duplicates for later cleanup if needed.
        seen = set()
        alliances = []
        for a in raw_alliances:
            if a.alliance_number in seen:
                current_app.logger.info(f"Skipping duplicate alliance row id {a.id} for alliance_number {a.alliance_number} event {event_id}")
                continue
            seen.add(a.alliance_number)
            alliances.append(a)

        alliance_data = []
        for alliance in alliances:
            alliance_info = {
                'id': alliance.id,
                'alliance_number': alliance.alliance_number,
                'captain': None,
                'first_pick': None,
                'second_pick': None,
                'third_pick': None
            }

            # Get team info for each position
            for position in ['captain', 'first_pick', 'second_pick', 'third_pick']:
                team_id = getattr(alliance, position)
                if team_id:
                    team = Team.query.get(team_id)
                    if team:
                        alliance_info[position] = {
                            'team_id': team.id,
                            'team_number': team.team_number,
                            'team_name': team.team_name or f'Team {team.team_number}'
                        }

            alliance_data.append(alliance_info)

        return jsonify({
            'success': True,
            'alliances': alliance_data
        })
    except Exception as e:
        print(f"Error in get_alliances: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/api/team_metrics')
def team_metrics():
    """Return basic metrics for a team_number (useful for client-side UI updates).

    Query params:
      - team_number (required)
      - event_id (optional)
    """
    team_number = request.args.get('team_number')
    event_id = request.args.get('event_id', type=int)

    if not team_number:
        return jsonify({'error': 'team_number required'}), 400

    # Find the team
    team = Team.query.filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'error': 'Team not found'}), 404

    try:
        analytics_result = calculate_team_metrics(team.id, event_id=event_id)
        metrics = analytics_result.get('metrics', {}) or {}

        # Prefer 'total_points' then 'tot' or sum components as a fallback
        total = 0
        if 'total_points' in metrics:
            total = metrics.get('total_points', 0) or 0
        elif 'tot' in metrics:
            total = metrics.get('tot', 0) or 0
        else:
            # fallback to common component ids
            total = (metrics.get('apt', 0) or 0) + (metrics.get('tpt', 0) or 0) + (metrics.get('ept', 0) or 0)

        return jsonify({'team_number': team.team_number, 'total_points': round(float(total), 1)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/team_details')
def team_details():
    """Return detailed team context for alliances recommendations.

    Query params:
      - team_number (required)
      - event_param (optional): event id/code/alliance_<CODE>
    """
    team_number = request.args.get('team_number', type=int)
    event_param = request.args.get('event_param', '').strip()

    if not team_number:
        return jsonify({'success': False, 'error': 'team_number required'}), 400

    team = filter_teams_by_scouting_team().filter_by(team_number=team_number).first()
    if not team:
        team = Team.query.filter_by(team_number=team_number).first()

    if not team:
        return jsonify({'success': False, 'error': 'Team not found'}), 404

    def _resolve_event_scope(param):
        event_id_local = None
        event_code_local = ''
        scoped_ids = []

        if param:
            event_id_local = resolve_event_id_from_param(param)
            if event_id_local is None and param.isdigit():
                event_id_local = int(param)

        event_obj = Event.query.get(event_id_local) if event_id_local else None
        if event_obj and getattr(event_obj, 'code', None):
            event_code_local = (event_obj.code or '').strip().upper()
        elif param:
            raw = str(param).strip()
            if raw.startswith('alliance_'):
                event_code_local = raw[len('alliance_'):].strip().upper()
            elif not raw.isdigit():
                event_code_local = raw.upper()

        if event_code_local:
            code_variants = [event_code_local]
            if len(event_code_local) > 4 and event_code_local[:4].isdigit():
                code_variants.append(event_code_local[4:])

            scoped_ids = [
                row[0] for row in Event.query.with_entities(Event.id)
                .filter(func.upper(Event.code).in_(code_variants)).all()
            ]

        if event_id_local is not None and event_id_local not in scoped_ids:
            scoped_ids.append(event_id_local)

        return event_id_local, event_code_local, scoped_ids

    event_id, event_code, scoped_event_ids = _resolve_event_scope(event_param)
    game_config = get_effective_game_config()

    def _entry_total_points(entry):
        try:
            auto_pts = entry._calculate_auto_points_dynamic(entry.data, game_config)
            teleop_pts = entry._calculate_teleop_points_dynamic(entry.data, game_config)
            endgame_pts = entry._calculate_endgame_points_dynamic(entry.data, game_config)
            return round(float(auto_pts + teleop_pts + endgame_pts), 1)
        except Exception:
            try:
                data = entry.data if isinstance(entry.data, dict) else {}
                total = sum(float(v) for v in data.values() if isinstance(v, (int, float)))
                return round(total, 1)
            except Exception:
                return 0.0

    def _entry_component_points(entry):
        try:
            auto_pts = float(entry._calculate_auto_points_dynamic(entry.data, game_config) or 0)
            teleop_pts = float(entry._calculate_teleop_points_dynamic(entry.data, game_config) or 0)
            endgame_pts = float(entry._calculate_endgame_points_dynamic(entry.data, game_config) or 0)
            return auto_pts, teleop_pts, endgame_pts
        except Exception:
            return 0.0, 0.0, 0.0

    scouting_entries, _ = get_scouting_data_for_team(team.id, event_id=event_id if isinstance(event_id, int) else None)

    filtered_entries = []
    for entry in scouting_entries:
        match_obj = getattr(entry, 'match', None)
        if not match_obj:
            continue
        if scoped_event_ids and getattr(match_obj, 'event_id', None) not in scoped_event_ids:
            continue
        if event_code:
            match_code = ((getattr(match_obj, 'event', None) and getattr(match_obj.event, 'code', None)) or '').upper()
            if match_code and match_code != event_code:
                continue
        filtered_entries.append(entry)

    # Build event-scoped match list for this team so we can fill gaps with estimates.
    team_matches = []
    if scoped_event_ids:
        candidate_matches = Match.query.filter(Match.event_id.in_(scoped_event_ids)).order_by(*Match.schedule_order()).all()
        for m in candidate_matches:
            try:
                if team.team_number in (m.red_teams + m.blue_teams):
                    team_matches.append(m)
            except Exception:
                continue

    # Deduplicate mirrored matches that can occur when alliance members each have
    # their own local Event rows for the same event code.
    deduped_matches = {}
    for m in team_matches:
        match_key = (
            (getattr(m, 'comp_level', None) or '').lower(),
            int(getattr(m, 'set_number', 0) or 0),
            int(getattr(m, 'match_number', 0) or 0),
            str(getattr(m, 'match_type', '') or '').lower(),
        )
        if match_key not in deduped_matches:
            deduped_matches[match_key] = m
    team_matches = list(deduped_matches.values())

    match_points = []
    total_points_accum = 0.0
    auto_points_accum = 0.0
    teleop_points_accum = 0.0
    endgame_points_accum = 0.0
    for entry in sorted(filtered_entries, key=lambda e: (getattr(getattr(e, 'match', None), 'match_number', 0) or 0)):
        match_obj = entry.match
        pts = _entry_total_points(entry)
        auto_pts, teleop_pts, endgame_pts = _entry_component_points(entry)
        total_points_accum += pts
        auto_points_accum += auto_pts
        teleop_points_accum += teleop_pts
        endgame_points_accum += endgame_pts
        match_points.append({
            'match_id': match_obj.id,
            'match_number': match_obj.match_number,
            'match_type': match_obj.match_type,
            'alliance': getattr(entry, 'alliance', None),
            'points': pts,
            'scout_name': getattr(entry, 'scout_name', '') or 'Unknown',
            'timestamp': getattr(entry, 'timestamp', None).isoformat() if getattr(entry, 'timestamp', None) else None,
            'points_source': 'scouted',
            'is_estimate': False
        })

    # Fill missing match rows with per-match historical Statbotics EPA estimates.
    statbotics_estimate = None
    statbotics_by_match = {}

    def _normalize_comp_level(match_obj):
        level = (getattr(match_obj, 'comp_level', None) or '').lower()
        if level in ('qm', 'ef', 'qf', 'sf', 'f'):
            return level
        mtype = (getattr(match_obj, 'match_type', None) or '').strip().lower()
        if 'qual' in mtype:
            return 'qm'
        if 'playoff' in mtype or 'elim' in mtype:
            return 'qf'
        return ''

    def _parse_statbotics_match_key(key):
        # Example keys: 2025cabe_qm12, 2025cabe_qf1m2, 2025cabe_f1m1
        text = str(key or '')
        m = re.search(r'_(qm|ef|qf|sf|f)(\d+)(?:m(\d+))?$', text)
        if not m:
            return None
        comp = m.group(1)
        left = int(m.group(2) or 0)
        right = int(m.group(3) or 0)
        if comp == 'qm':
            return comp, 0, left
        return comp, left, right

    if team_matches:
        event_keys = []
        events_for_scope = Event.query.filter(Event.id.in_(scoped_event_ids)).all() if scoped_event_ids else []
        for ev in events_for_scope:
            code = str(getattr(ev, 'code', '') or '').strip().lower()
            year = getattr(ev, 'year', None)
            if not code:
                continue
            if year and not code.startswith(str(year)):
                event_keys.append(f"{year}{code}")
            event_keys.append(code)

        # Keep order but remove duplicates.
        seen_event_keys = set()
        event_keys = [k for k in event_keys if not (k in seen_event_keys or seen_event_keys.add(k))]

        statbotics_rows = []
        for key in event_keys:
            rows = get_statbotics_team_matches(team.team_number, event_key=key, limit=300)
            if rows:
                statbotics_rows = rows
                break

        for row in statbotics_rows:
            parsed = _parse_statbotics_match_key(row.get('match'))
            if not parsed:
                continue
            sb_comp, sb_set, sb_match_num = parsed
            sb_points = (((row.get('epa') or {}).get('total_points')) if isinstance(row.get('epa'), dict) else None)
            if sb_points is None:
                continue
            sb_alliance = row.get('alliance')
            statbotics_by_match[(sb_comp, int(sb_set), int(sb_match_num), str(sb_alliance or ''))] = round(max(float(sb_points), 0.0), 1)

        # Fallback single estimate if no per-match history is available.
        if not statbotics_by_match:
            raw_estimate = (get_epa_metrics_for_team(team.team_number) or {}).get('total')
            if raw_estimate is not None:
                statbotics_estimate = round(max(float(raw_estimate), 0.0), 1)

    scouted_match_ids = {row.get('match_id') for row in match_points if row.get('match_id') is not None}
    if team_matches:
        for m in team_matches:
            if m.id in scouted_match_ids:
                continue
            if team.team_number in m.red_teams:
                alliance_side = 'red'
            elif team.team_number in m.blue_teams:
                alliance_side = 'blue'
            else:
                alliance_side = None

            comp_level = _normalize_comp_level(m)
            set_number = int(getattr(m, 'set_number', 0) or 0)
            match_number = int(getattr(m, 'match_number', 0) or 0)
            estimate = statbotics_by_match.get((comp_level, set_number, match_number, str(alliance_side or '')))

            # Some sources omit alliance side; try without it.
            if estimate is None:
                for key_tuple, val in statbotics_by_match.items():
                    if key_tuple[:3] == (comp_level, set_number, match_number):
                        estimate = val
                        break

            if estimate is None:
                estimate = statbotics_estimate

            if estimate is None:
                continue

            total_points_accum += estimate
            match_points.append({
                'match_id': m.id,
                'match_number': m.match_number,
                'match_type': m.match_type,
                'alliance': alliance_side,
                'points': estimate,
                'scout_name': 'Statbotics Historical Estimate',
                'timestamp': getattr(m, 'scheduled_time', None).isoformat() if getattr(m, 'scheduled_time', None) else None,
                'points_source': 'statbotics',
                'is_estimate': True
            })

    match_points.sort(key=lambda row: (row.get('match_number') if row.get('match_number') is not None else 9999, row.get('is_estimate', False)))

    qualitative_entries, _, _ = get_all_qualitative_data(event_ids=scoped_event_ids if scoped_event_ids else None)
    qualitative_notes = []
    team_key = f'team_{team.team_number}'
    for qentry in qualitative_entries:
        qdata = qentry.data if isinstance(getattr(qentry, 'data', None), dict) else {}
        for alliance_key in ['red', 'blue', 'individual']:
            alliance_data = qdata.get(alliance_key, {})
            if not isinstance(alliance_data, dict):
                continue
            tdata = alliance_data.get(team_key)
            if not isinstance(tdata, dict):
                continue
            note = str(tdata.get('notes') or '').strip()
            if not note:
                continue
            qmatch = getattr(qentry, 'match', None)
            qualitative_notes.append({
                'match_id': qmatch.id if qmatch else None,
                'match_number': qmatch.match_number if qmatch else None,
                'alliance': alliance_key,
                'notes': note,
                'scout_name': getattr(qentry, 'scout_name', '') or 'Unknown',
                'timestamp': qentry.timestamp.isoformat() if getattr(qentry, 'timestamp', None) else None
            })

    qualitative_notes.sort(key=lambda n: (n['match_number'] if n['match_number'] is not None else 9999))

    pit_entries, _, _ = get_all_pit_data(team_number=team.team_number)
    pit_summary = []
    for p in pit_entries:
        pdata = p.data if isinstance(getattr(p, 'data', None), dict) else {}
        # Keep the payload small but useful.
        compact = {}
        for k, v in list(pdata.items())[:8]:
            compact[str(k)] = v
        pit_summary.append({
            'scout_name': getattr(p, 'scout_name', '') or 'Unknown',
            'timestamp': p.timestamp.isoformat() if getattr(p, 'timestamp', None) else None,
            'data': compact
        })

    def _latest_iso(values):
        cleaned = [v for v in values if v]
        if not cleaned:
            return None
        return max(cleaned)

    scouted_only_rows = [m for m in match_points if not m.get('is_estimate')]
    unique_scouts = {str(m.get('scout_name') or '').strip() for m in scouted_only_rows if m.get('scout_name')}
    unique_scouts.discard('')

    detected_event = Event.query.filter(Event.id.in_(scoped_event_ids)).first() if scoped_event_ids else None
    event_context = {
        'event_code': (detected_event.code if detected_event and getattr(detected_event, 'code', None) else event_code),
        'event_name': (detected_event.name if detected_event and getattr(detected_event, 'name', None) else None),
        'event_year': (detected_event.year if detected_event and getattr(detected_event, 'year', None) else None),
        'event_rows_in_scope': len(scoped_event_ids),
    }

    return jsonify({
        'success': True,
        'team': {
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'location': team.location,
            'scouting_team_number': getattr(team, 'scouting_team_number', None),
            'starting_points': team.starting_points,
            'starting_points_enabled': bool(getattr(team, 'starting_points_enabled', False)),
        },
        'event': event_context,
        'summary': {
            'match_count': len(match_points),
            'average_points': round((total_points_accum / len(match_points)), 1) if match_points else 0,
            'total_points': round(total_points_accum, 1),
            'average_auto_points': round((auto_points_accum / len(filtered_entries)), 1) if filtered_entries else 0,
            'average_teleop_points': round((teleop_points_accum / len(filtered_entries)), 1) if filtered_entries else 0,
            'average_endgame_points': round((endgame_points_accum / len(filtered_entries)), 1) if filtered_entries else 0,
            'qualitative_notes_count': len(qualitative_notes),
            'pit_entries_count': len(pit_summary),
            'estimated_matches_count': len([m for m in match_points if m.get('is_estimate')]),
            'scouted_matches_count': len([m for m in match_points if not m.get('is_estimate')]),
            'distinct_scouts_count': len(unique_scouts),
            'latest_scouted_match_at': _latest_iso([m.get('timestamp') for m in scouted_only_rows]),
            'latest_qual_note_at': _latest_iso([n.get('timestamp') for n in qualitative_notes]),
            'latest_pit_entry_at': _latest_iso([p.get('timestamp') for p in pit_summary]),
            'statbotics_estimate': statbotics_estimate,
        },
        'match_points': match_points,
        'qualitative_notes': qualitative_notes,
        'pit_data': pit_summary[:5],
    })

@bp.route('/api/remove_from_list', methods=['POST'])
def remove_from_list():
    """Remove a team from avoid or do not pick list"""
    data = request.get_json()
    
    team_id = data.get('team_id')
    event_id = data.get('event_id')
    list_type = data.get('list_type')  # 'avoid' or 'do_not_pick'
    
    if not all([team_id, event_id, list_type]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    if list_type not in ['avoid', 'do_not_pick', 'declined']:
        return jsonify({'success': False, 'message': 'Invalid list type'})
    
    # Find and remove the entry
    if list_type == 'avoid':
        entry = AvoidEntry.query.filter_by(team_id=team_id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
    else:  # do_not_pick or declined
        if list_type == 'do_not_pick':
            entry = DoNotPickEntry.query.filter_by(team_id=team_id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
        else:
            entry = DeclinedEntry.query.filter_by(team_id=team_id, event_id=event_id, scouting_team_number=current_user.scouting_team_number).first()
    
    if not entry:
        return jsonify({'success': False, 'message': 'Entry not found'})
    
    try:
        team = entry.team  # Get team info before deleting
        db.session.delete(entry)
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team_id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': list_type,
            'action': 'remove'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': f'Team removed from {list_type.replace("_", " ")} list'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/team_tags/add', methods=['POST'])
def add_team_tags():
    """Add or update tags for a team in an event. Supports both legacy offense/defense tags and new custom tags."""
    data = request.get_json() or {}

    team_number = data.get('team_number')
    event_id = data.get('event_id')
    offense_tag = bool(data.get('offense_tag', False))
    defense_tag = bool(data.get('defense_tag', False))
    custom_tags = data.get('custom_tags', '')
    note = data.get('note', '')

    if not all([team_number, event_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})

    # Validate that at least one tag is provided (custom or legacy)
    tags_list = []
    if custom_tags:
        if isinstance(custom_tags, str):
            tags_list = [t.strip() for t in custom_tags.split() if t.strip()]
        elif isinstance(custom_tags, list):
            tags_list = [str(t).strip() for t in custom_tags if t]
    
    if not tags_list and not offense_tag and not defense_tag:
        return jsonify({'success': False, 'message': 'Add at least one tag (custom tags or Offense/Defense)'})

    team = filter_teams_by_scouting_team().filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})

    try:
        existing = TeamTagEntry.query.filter_by(
            team_id=team.id,
            event_id=event_id,
            scouting_team_number=current_user.scouting_team_number
        ).first()

        encoded = _encode_team_tag_meta(note, custom_tags=tags_list, offense_tag=offense_tag, defense_tag=defense_tag)

        if existing:
            existing.reason = encoded
        else:
            existing = TeamTagEntry(
                team_id=team.id,
                event_id=event_id,
                reason=encoded,
                scouting_team_number=current_user.scouting_team_number
            )
            db.session.add(existing)

        db.session.commit()

        emit_recommendations_update(event_id)
        return jsonify({
            'success': True,
            'message': f'Tags saved for Team {team.team_number}',
            'team_id': team.id,
            'team_number': team.team_number,
            'custom_tags': tags_list,
            'offense_tag': offense_tag,
            'defense_tag': defense_tag,
            'note': (note or '').strip()[:120]
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/team_tags/remove', methods=['POST'])
def remove_team_tags():
    """Remove offense/defense tags entry for a team in an event."""
    data = request.get_json() or {}

    team_id = data.get('team_id')
    event_id = data.get('event_id')

    if not all([team_id, event_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})

    entry = TeamTagEntry.query.filter_by(
        team_id=team_id,
        event_id=event_id,
        scouting_team_number=current_user.scouting_team_number
    ).first()

    if not entry:
        return jsonify({'success': False, 'message': 'Tag entry not found'})

    try:
        db.session.delete(entry)
        db.session.commit()
        emit_recommendations_update(event_id)
        return jsonify({'success': True, 'message': 'Team tags removed'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/team_tags/clear_all', methods=['POST'])
def clear_all_team_tags():
    """Clear all team tags for an event."""
    data = request.get_json() or {}
    event_id = data.get('event_id')

    if not event_id:
        return jsonify({'success': False, 'message': 'Missing event_id'})

    try:
        # Delete all team tag entries for this event and scouting team
        TeamTagEntry.query.filter_by(
            event_id=event_id,
            scouting_team_number=current_user.scouting_team_number
        ).delete()
        db.session.commit()
        emit_recommendations_update(event_id)
        return jsonify({'success': True, 'message': 'All team tags cleared'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/team_tags/get/<int:event_id>')
def get_team_tags(event_id):
    """Get all team tag entries for an event."""
    try:
        entries = TeamTagEntry.query.filter_by(
            event_id=event_id,
            scouting_team_number=current_user.scouting_team_number
        ).join(Team).order_by(Team.team_number).all()

        team_tags = []
        for entry in entries:
            meta = _decode_team_tag_meta(entry.reason)
            team_tags.append({
                'team_id': entry.team_id,
                'team_number': entry.team.team_number,
                'team_name': entry.team.team_name or f'Team {entry.team.team_number}',
                'custom_tags': meta.get('custom_tags', []),
                'offense_tag': meta['offense_tag'],
                'defense_tag': meta['defense_tag'],
                'note': meta['note']
            })

        return jsonify({'success': True, 'team_tags': team_tags})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})


@bp.route('/api/want_list/add', methods=['POST'])
def add_to_want_list():
    """Add a team to the want list"""
    data = request.get_json()
    
    team_number = data.get('team_number')
    event_id = data.get('event_id')
    reason = data.get('reason', '')
    
    if not all([team_number, event_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Get the team
    team = filter_teams_by_scouting_team().filter_by(team_number=team_number).first()
    if not team:
        return jsonify({'success': False, 'message': 'Team not found'})
    
    # Check if team is already in the want list
    existing = filter_want_list_by_scouting_team().filter_by(
        team_id=team.id, 
        event_id=event_id
    ).first()
    if existing:
        return jsonify({'success': False, 'message': 'Team already in want list'})
    
    try:
        # Get the highest rank currently in the list and add 1
        max_rank_result = filter_want_list_by_scouting_team().filter_by(
            event_id=event_id
        ).order_by(WantListEntry.rank.desc()).first()
        
        new_rank = (max_rank_result.rank + 1) if max_rank_result else 1
        
        entry = WantListEntry(
            team_id=team.id, 
            event_id=event_id, 
            reason=reason, 
            rank=new_rank,
            scouting_team_number=current_user.scouting_team_number
        )
        db.session.add(entry)
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': 'want_list',
            'rank': new_rank,
            'reason': reason,
            'action': 'add'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({
            'success': True, 
            'message': f'Team {team_number} added to want list',
            'rank': new_rank,
            'entry_id': entry.id
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/want_list/remove', methods=['POST'])
def remove_from_want_list():
    """Remove a team from the want list"""
    data = request.get_json()
    
    team_id = data.get('team_id')
    event_id = data.get('event_id')
    
    if not all([team_id, event_id]):
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    # Find and remove the entry
    entry = filter_want_list_by_scouting_team().filter_by(
        team_id=team_id, 
        event_id=event_id
    ).first()
    
    if not entry:
        return jsonify({'success': False, 'message': 'Entry not found'})
    
    try:
        team = entry.team  # Get team info before deleting
        removed_rank = entry.rank
        db.session.delete(entry)
        
        # Re-rank remaining entries to fill the gap
        remaining_entries = filter_want_list_by_scouting_team().filter_by(
            event_id=event_id
        ).filter(WantListEntry.rank > removed_rank).order_by(WantListEntry.rank).all()
        
        for remaining_entry in remaining_entries:
            remaining_entry.rank -= 1
        
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'team_id': team_id,
            'team_number': team.team_number,
            'team_name': team.team_name or f'Team {team.team_number}',
            'list_type': 'want_list',
            'action': 'remove'
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': 'Team removed from want list'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/want_list/reorder', methods=['POST'])
def reorder_want_list():
    """Reorder teams in the want list"""
    data = request.get_json()
    
    event_id = data.get('event_id')
    ordered_team_ids = data.get('ordered_team_ids', [])  # Array of team IDs in new order
    
    if not event_id or not ordered_team_ids:
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    try:
        # Update ranks based on new order
        for new_rank, team_id in enumerate(ordered_team_ids, start=1):
            entry = filter_want_list_by_scouting_team().filter_by(
                team_id=team_id,
                event_id=event_id
            ).first()
            if entry:
                entry.rank = new_rank
        
        db.session.commit()
        
        # Emit real-time update
        list_data = {
            'event_id': event_id,
            'list_type': 'want_list',
            'action': 'reorder',
            'ordered_team_ids': ordered_team_ids
        }
        emit_lists_update(event_id, list_data)
        emit_recommendations_update(event_id)
        
        return jsonify({'success': True, 'message': 'Want list reordered successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'})


@bp.route('/api/want_list/get/<int:event_id>')
def get_want_list(event_id):
    """Get the want list for an event"""
    try:
        entries = filter_want_list_by_scouting_team().filter_by(
            event_id=event_id
        ).order_by(WantListEntry.rank).all()
        
        want_list = []
        for entry in entries:
            meta = _decode_pick_meta(entry.reason)
            want_list.append({
                'id': entry.id,
                'team_id': entry.team_id,
                'team_number': entry.team.team_number,
                'team_name': entry.team.team_name or f'Team {entry.team.team_number}',
                'rank': entry.rank,
                'reason': meta['note']
            })
        
        return jsonify({'success': True, 'want_list': want_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})
