"""
Main API Routes for Data Access and Operations
Provides comprehensive API endpoints for accessing team data, sync operations, and actions
"""
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
import traceback
import json

from app.utils.api_auth import (
    team_data_access_required, scouting_data_read_required, scouting_data_write_required,
    sync_operations_required, analytics_access_required, get_current_api_team,
    get_current_api_key, has_api_permission
)
from app.models import (
    Team, Event, Match, ScoutingData, User, Role, 
    DoNotPickEntry, AvoidEntry
)
from app import db
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team,
    filter_scouting_data_by_scouting_team, get_current_scouting_team_number
)

bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')


@bp.route('/info', methods=['GET'])
@team_data_access_required
def api_info():
    """Get API information and current key status"""
    api_key = get_current_api_key()
    team_number = get_current_api_team()
    
    return jsonify({
        'success': True,
        'api_version': '1.0',
        'api_key': {
            'id': api_key.id,
            'name': api_key.name,
            'team_number': team_number,
            'permissions': api_key.permissions,
            'rate_limit_per_hour': api_key.rate_limit_per_hour,
            'created_at': api_key.created_at.isoformat(),
            'last_used_at': api_key.last_used_at.isoformat() if api_key.last_used_at else None
        },
        'server_time': datetime.utcnow().isoformat(),
        'endpoints': {
            'teams': '/api/v1/teams',
            'team_details': '/api/v1/teams/{team_id}',
            'events': '/api/v1/events',
            'event_details': '/api/v1/events/{event_id}',
            'matches': '/api/v1/matches',
            'match_details': '/api/v1/matches/{match_id}',
            'scouting_data': '/api/v1/scouting-data',
            'team_performance': '/api/v1/analytics/team-performance',
            'sync_status': '/api/v1/sync/status',
            'sync_trigger': '/api/v1/sync/trigger',
            'do_not_pick_list': '/api/v1/team-lists/do-not-pick',
            'health_check': '/api/v1/health'
        }
    })


# Team Data Endpoints
@bp.route('/teams', methods=['GET'])
@team_data_access_required
def get_teams():
    """Get teams data filtered by API key's scouting team"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Start with teams filtered by API key's scouting team
        teams_query = Team.query.filter(Team.scouting_team_number == api_team_number)
        
        # Add filters
        event_id = request.args.get('event_id', type=int)
        if event_id:
            teams_query = teams_query.join(Team.events).filter(Event.id == event_id)
        
        team_number_filter = request.args.get('team_number', type=int)
        if team_number_filter:
            teams_query = teams_query.filter(Team.team_number == team_number_filter)
        
        # Add pagination
        limit = request.args.get('limit', 100, type=int)
        if limit > 1000:
            limit = 1000
        
        offset = request.args.get('offset', 0, type=int)
        
        teams = teams_query.offset(offset).limit(limit).all()
        total_count = teams_query.count()
        
        teams_data = []
        for team in teams:
            team_data = {
                'id': team.id,
                'team_number': team.team_number,
                'team_name': team.team_name,
                'location': team.location,
                'scouting_team_number': team.scouting_team_number,
                'events': [{'id': e.id, 'name': e.name, 'code': e.code} for e in team.events]
            }
            teams_data.append(team_data)
        
        return jsonify({
            'success': True,
            'teams': teams_data,
            'count': len(teams_data),
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
            'requesting_team': api_team_number
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting teams: {str(e)}")
        return jsonify({'error': 'Failed to retrieve teams'}), 500


@bp.route('/teams/<int:team_id>', methods=['GET'])
@team_data_access_required
def get_team_details(team_id):
    """Get detailed information about a specific team (filtered by API key's scouting team)"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Get team with team isolation
        team = Team.query.filter(Team.id == team_id, Team.scouting_team_number == api_team_number).first()
        
        if not team:
            return jsonify({'error': 'Team not found or not accessible to your API key\'s scouting team'}), 404
        
        # Get team's scouting data (filtered by API key's scouting team)
        scouting_data = ScoutingData.query.filter(ScoutingData.team_id == team_id, ScoutingData.scouting_team_number == api_team_number).all()
        
        team_data = {
            'id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name,
            'location': team.location,
            'scouting_team_number': team.scouting_team_number,
            'events': [{'id': e.id, 'name': e.name, 'code': e.code} for e in team.events],
            'scouting_data_count': len(scouting_data),
            'recent_matches': []
        }
        
        # Get recent match data (all matches involving this team)
        recent_matches = Match.query.filter(
            db.or_(
                Match.red_alliance.contains(str(team.team_number)),
                Match.blue_alliance.contains(str(team.team_number))
            )
        ).order_by(Match.id.desc()).limit(10).all()
        
        for match in recent_matches:
            team_data['recent_matches'].append({
                'id': match.id,
                'match_number': match.match_number,
                'match_type': match.match_type,
                'red_alliance': match.red_alliance,
                'blue_alliance': match.blue_alliance,
                'red_score': match.red_score,
                'blue_score': match.blue_score,
                'winner': match.winner
            })
        
        return jsonify({
            'success': True,
            'team': team_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting team details: {str(e)}")
        return jsonify({'error': 'Failed to retrieve team details'}), 500


# Event Data Endpoints
@bp.route('/events', methods=['GET'])
@team_data_access_required
def get_events():
    """Get events that have teams associated with API key's scouting team"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Start with events that have teams belonging to the API key's scouting team
        events_query = Event.query.join(Event.teams).filter(Team.scouting_team_number == api_team_number).distinct()
        
        # Add filters
        event_code = request.args.get('code')
        if event_code:
            events_query = events_query.filter(Event.code.ilike(f'%{event_code}%'))
        
        location = request.args.get('location')
        if location:
            events_query = events_query.filter(Event.location.ilike(f'%{location}%'))
        
        # Add pagination
        limit = request.args.get('limit', 100, type=int)
        if limit > 1000:
            limit = 1000
        
        offset = request.args.get('offset', 0, type=int)
        
        events = events_query.offset(offset).limit(limit).all()
        total_count = events_query.count()
        
        events_data = []
        for event in events:
            event_data = {
                'id': event.id,
                'name': event.name,
                'code': event.code,
                'location': event.location,
                'start_date': event.start_date.isoformat() if event.start_date else None,
                'end_date': event.end_date.isoformat() if event.end_date else None,
                'team_count': len(event.teams)
            }
            events_data.append(event_data)
        
        return jsonify({
            'success': True,
            'events': events_data,
            'count': len(events_data),
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting events: {str(e)}")
        return jsonify({'error': 'Failed to retrieve events'}), 500


@bp.route('/events/<int:event_id>', methods=['GET'])
@team_data_access_required
def get_event_details(event_id):
    """Get detailed information about a specific event (only if it has teams from API key's scouting team)"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Get event only if it has teams belonging to the API key's scouting team
        event = Event.query.join(Event.teams).filter(
            Event.id == event_id,
            Team.scouting_team_number == api_team_number
        ).first()
        
        if not event:
            return jsonify({'error': 'Event not found or not accessible to your API key\'s scouting team'}), 404
        
        if not event:
            return jsonify({'error': 'Event not found'}), 404
        
        # Get teams and matches for this event
        event_teams = event.teams
        event_matches = Match.query.filter(Match.event_id == event_id).all()
        
        event_data = {
            'id': event.id,
            'name': event.name,
            'code': event.code,
            'location': event.location,
            'start_date': event.start_date.isoformat() if event.start_date else None,
            'end_date': event.end_date.isoformat() if event.end_date else None,
            'team_count': len(event_teams),
            'match_count': len(event_matches),
            'teams': [{'id': t.id, 'team_number': t.team_number, 'team_name': t.team_name} for t in event_teams],
            'recent_matches': []
        }
        
        # Get recent matches
        recent_matches = sorted(event_matches, key=lambda x: x.match_number, reverse=True)[:10]
        for match in recent_matches:
            event_data['recent_matches'].append({
                'id': match.id,
                'match_number': match.match_number,
                'match_type': match.match_type,
                'red_alliance': match.red_alliance,
                'blue_alliance': match.blue_alliance,
                'red_score': match.red_score,
                'blue_score': match.blue_score,
                'winner': match.winner
            })
        
        return jsonify({
            'success': True,
            'event': event_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting event details: {str(e)}")
        return jsonify({'error': 'Failed to retrieve event details'}), 500


# Match Data Endpoints
@bp.route('/matches', methods=['GET'])
@scouting_data_read_required
def get_matches():
    """Get matches filtered by events that have teams from API key's scouting team"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Start with matches from events that have teams belonging to the API key's scouting team
        matches_query = Match.query.join(Match.event).join(Event.teams).filter(
            Team.scouting_team_number == api_team_number
        ).distinct()
        
        # Add filters
        event_id = request.args.get('event_id', type=int)
        if event_id:
            matches_query = matches_query.filter(Match.event_id == event_id)
        
        match_type = request.args.get('match_type')
        if match_type:
            matches_query = matches_query.filter(Match.match_type.ilike(f'%{match_type}%'))
        
        team_number = request.args.get('team_number', type=int)
        if team_number:
            team_str = str(team_number)
            matches_query = matches_query.filter(
                db.or_(
                    Match.red_alliance.contains(team_str),
                    Match.blue_alliance.contains(team_str)
                )
            )
        
        match_number = request.args.get('match_number', type=int)
        if match_number:
            matches_query = matches_query.filter(Match.match_number == match_number)
        
        # Add pagination
        limit = request.args.get('limit', 100, type=int)
        if limit > 1000:
            limit = 1000
        
        offset = request.args.get('offset', 0, type=int)
        
        matches = matches_query.order_by(Match.match_number).offset(offset).limit(limit).all()
        total_count = matches_query.count()
        
        matches_data = []
        for match in matches:
            match_data = {
                'id': match.id,
                'match_number': match.match_number,
                'match_type': match.match_type,
                'event_id': match.event_id,
                'red_alliance': match.red_alliance,
                'blue_alliance': match.blue_alliance,
                'red_score': match.red_score,
                'blue_score': match.blue_score,
                'winner': match.winner,
                'scouting_team_number': match.scouting_team_number
            }
            matches_data.append(match_data)
        
        return jsonify({
            'success': True,
            'matches': matches_data,
            'count': len(matches_data),
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting matches: {str(e)}")
        return jsonify({'error': 'Failed to retrieve matches'}), 500


@bp.route('/matches/<int:match_id>', methods=['GET'])
@scouting_data_read_required
def get_match_details(match_id):
    """Get detailed information about a specific match (only if from events with API key's teams)"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Get match only if it's from an event that has teams belonging to the API key's scouting team
        match = Match.query.join(Match.event).join(Event.teams).filter(
            Match.id == match_id,
            Team.scouting_team_number == api_team_number
        ).first()
        
        if not match:
            return jsonify({'error': 'Match not found or not accessible to your API key\'s scouting team'}), 404
        
        # Get scouting data for this match (filtered by API key's scouting team)
        scouting_data = ScoutingData.query.filter(
            ScoutingData.match_id == match_id,
            ScoutingData.scouting_team_number == api_team_number
        ).all()
        
        match_data = {
            'id': match.id,
            'match_number': match.match_number,
            'match_type': match.match_type,
            'event_id': match.event_id,
            'red_alliance': match.red_alliance,
            'blue_alliance': match.blue_alliance,
            'red_score': match.red_score,
            'blue_score': match.blue_score,
            'winner': match.winner,
            'scouting_team_number': match.scouting_team_number,
            'scouting_data_count': len(scouting_data),
            'scouting_entries': []
        }
        
        # Add scouting entries
        for data in scouting_data:
            match_data['scouting_entries'].append({
                'id': data.id,
                'team_id': data.team_id,
                'scout': data.scout,
                'timestamp': data.timestamp.isoformat() if data.timestamp else None,
                'scouting_team_number': data.scouting_team_number
            })
        
        return jsonify({
            'success': True,
            'match': match_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting match details: {str(e)}")
        return jsonify({'error': 'Failed to retrieve match details'}), 500


# Scouting Data Endpoints
@bp.route('/scouting-data', methods=['GET'])
@scouting_data_read_required
def get_scouting_data():
    """Get scouting data filtered by API key's scouting team"""
    try:
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Start with scouting data filtered by API key's scouting team
        scouting_query = ScoutingData.query.filter(ScoutingData.scouting_team_number == api_team_number)
        
        # Add filters
        team_id = request.args.get('team_id', type=int)
        if team_id:
            scouting_query = scouting_query.filter(ScoutingData.team_id == team_id)
        
        match_id = request.args.get('match_id', type=int)
        if match_id:
            scouting_query = scouting_query.filter(ScoutingData.match_id == match_id)
        
        scout = request.args.get('scout')
        if scout:
            scouting_query = scouting_query.filter(ScoutingData.scout.ilike(f'%{scout}%'))
        
        # Add pagination
        limit = request.args.get('limit', 100, type=int)
        if limit > 1000:
            limit = 1000
        
        offset = request.args.get('offset', 0, type=int)
        
        scouting_data = scouting_query.order_by(ScoutingData.id.desc()).offset(offset).limit(limit).all()
        total_count = scouting_query.count()
        
        scouting_data_list = []
        for data in scouting_data:
            scouting_data_item = {
                'id': data.id,
                'team_id': data.team_id,
                'match_id': data.match_id,
                'data': data.data,
                'scout': data.scout,
                'timestamp': data.timestamp.isoformat() if data.timestamp else None,
                'scouting_team_number': data.scouting_team_number
            }
            scouting_data_list.append(scouting_data_item)
        
        return jsonify({
            'success': True,
            'scouting_data': scouting_data_list,
            'count': len(scouting_data_list),
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting scouting data: {str(e)}")
        return jsonify({'error': 'Failed to retrieve scouting data'}), 500


@bp.route('/scouting-data', methods=['POST'])
@scouting_data_write_required
def create_scouting_data():
    """Create new scouting data entry"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        required_fields = ['team_id', 'match_id', 'data', 'scout']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Verify team and match exist (no team isolation)
        team = Team.query.filter(Team.id == data['team_id']).first()
        if not team:
            return jsonify({'error': 'Team not found'}), 404
        
        match = Match.query.filter(Match.id == data['match_id']).first()
        if not match:
            return jsonify({'error': 'Match not found'}), 404
        
        # Create scouting data entry
        scouting_data = ScoutingData(
            team_id=data['team_id'],
            match_id=data['match_id'],
            data=data['data'],
            scout=data['scout'],
            scouting_team_number=get_current_api_team()
        )
        
        db.session.add(scouting_data)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Scouting data created successfully',
            'scouting_data': {
                'id': scouting_data.id,
                'team_id': scouting_data.team_id,
                'match_id': scouting_data.match_id,
                'scout': scouting_data.scout,
                'timestamp': scouting_data.timestamp.isoformat()
            }
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Error creating scouting data: {str(e)}")
        return jsonify({'error': 'Failed to create scouting data'}), 500


# Analytics Endpoints
@bp.route('/analytics/team-performance', methods=['GET'])
@analytics_access_required
def get_team_performance():
    """Get team performance analytics for teams in API key's registered scouting team scope"""
    try:
        team_id = request.args.get('team_id', type=int)
        team_number = request.args.get('team_number', type=int)
        event_id = request.args.get('event_id', type=int)
        
        if not team_id and not team_number:
            return jsonify({'error': 'team_id or team_number parameter is required'}), 400
        
        # Get API key's registered team number for filtering
        api_team_number = get_current_api_team()
        if api_team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        
        # Find team by ID or number (filtered by API key's scouting team)
        if team_id:
            team = Team.query.filter(Team.id == team_id, Team.scouting_team_number == api_team_number).first()
        else:
            team = Team.query.filter(Team.team_number == team_number, Team.scouting_team_number == api_team_number).first()
        
        if not team:
            return jsonify({'error': 'Team not found or not accessible to your API key\'s scouting team'}), 404
        
        # Get scouting data for analytics (filtered by API key's scouting team)
        scouting_query = ScoutingData.query.filter(ScoutingData.team_id == team.id, ScoutingData.scouting_team_number == api_team_number)
        
        if event_id:
            scouting_query = scouting_query.join(ScoutingData.match).filter(Match.event_id == event_id)
        
        scouting_data = scouting_query.all()
        
        # Basic analytics
        total_entries = len(scouting_data)
        unique_matches = len(set(data.match_id for data in scouting_data))
        
        analytics_data = {
            'team_id': team.id,
            'team_number': team.team_number,
            'team_name': team.team_name,
            'total_scouting_entries': total_entries,
            'unique_matches_scouted': unique_matches,
            'data_quality_score': min(100, (total_entries / max(unique_matches, 1)) * 50),
            'last_scouted': max((data.timestamp for data in scouting_data), default=None)
        }
        
        if analytics_data['last_scouted']:
            analytics_data['last_scouted'] = analytics_data['last_scouted'].isoformat()
        
        return jsonify({
            'success': True,
            'analytics': analytics_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting team performance: {str(e)}")
        return jsonify({'error': 'Failed to retrieve team performance'}), 500


# Sync Operations Endpoints
@bp.route('/sync/status', methods=['GET'])
@sync_operations_required
def sync_status():
    """Get sync status and information"""
    try:
        team_number = get_current_api_team()
        
        # Get counts for all data (not team filtered)
        team_count = Team.query.count()
        match_count = Match.query.count()
        scouting_count = ScoutingData.query.count()
        event_count = Event.query.count()
        
        return jsonify({
            'success': True,
            'sync_status': {
                'team_number': team_number,
                'last_check': datetime.utcnow().isoformat(),
                'data_counts': {
                    'teams': team_count,
                    'matches': match_count,
                    'scouting_data': scouting_count,
                    'events': event_count
                },
                'sync_available': True
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting sync status: {str(e)}")
        return jsonify({'error': 'Failed to retrieve sync status'}), 500


@bp.route('/sync/trigger', methods=['POST'])
@sync_operations_required
def trigger_sync():
    """Trigger a sync operation"""
    try:
        data = request.get_json() or {}
        sync_type = data.get('type', 'full')  # full, teams, matches, scouting_data
        
        if sync_type not in ['full', 'teams', 'matches', 'scouting_data']:
            return jsonify({'error': 'Invalid sync type'}), 400
        
        # Here you could implement actual sync logic
        # For now, we'll simulate a sync operation
        
        return jsonify({
            'success': True,
            'message': f'{sync_type.title()} sync triggered successfully',
            'sync_id': f'sync_{int(datetime.utcnow().timestamp())}',
            'estimated_completion': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error triggering sync: {str(e)}")
        return jsonify({'error': 'Failed to trigger sync'}), 500


# Team Lists Endpoints (Do Not Pick, Avoid)
@bp.route('/team-lists/do-not-pick', methods=['GET'])
@team_data_access_required
def get_do_not_pick_list():
    """Get do not pick list for the team"""
    try:
        team_number = get_current_api_team()
        
        entries = DoNotPickEntry.query.filter_by(scouting_team_number=team_number).all()
        
        entries_data = []
        for entry in entries:
            entries_data.append({
                'id': entry.id,
                'team_id': entry.team_id,
                'team_number': entry.team.team_number if entry.team else None,
                'team_name': entry.team.team_name if entry.team else None,
                'reason': entry.reason,
                'timestamp': entry.timestamp.isoformat() if entry.timestamp else None
            })
        
        return jsonify({
            'success': True,
            'do_not_pick_list': entries_data,
            'count': len(entries_data)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting do not pick list: {str(e)}")
        return jsonify({'error': 'Failed to retrieve do not pick list'}), 500


# Health Check Endpoint
@bp.route('/health', methods=['GET'])
@team_data_access_required
def health_check():
    """API health check endpoint"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0',
        'team_number': get_current_api_team()
    })


@bp.route('/all', methods=['GET'])
@team_data_access_required
def api_dump_all():
    """Dump all data for the API key's associated scouting team.

    This endpoint is intended for administrative exports. It respects API key
    team scoping (get_current_api_team()). Supports api_key via header or
    query param (GET) as other API endpoints do.
    """
    try:
        team_number = get_current_api_team()
        if team_number is None:
            return jsonify({'error': 'API key not associated with a scouting team'}), 403
        # Use column-only queries to avoid lazy-loading relationships (which may pull User records)
        # Teams - select only scalar columns
        teams_rows = db.session.query(
            Team.id, Team.team_number, Team.team_name, Team.location
        ).filter(Team.scouting_team_number == team_number).all()
        teams_data = [
            {
                'id': row.id,
                'team_number': row.team_number,
                'team_name': row.team_name,
                'location': row.location
            }
            for row in teams_rows
        ]

        # Events - build a safe column list (only InstrumentedAttribute columns) to avoid passing property objects
        from sqlalchemy.orm.attributes import InstrumentedAttribute

        events_data = []
        event_cols = [Event.id, Event.name, Event.code]
        # helper to append if real column
        def add_if_column(attr_name):
            attr = getattr(Event, attr_name, None)
            if isinstance(attr, InstrumentedAttribute):
                event_cols.append(attr)

        add_if_column('location')
        add_if_column('start_date')
        add_if_column('end_date')

        query = db.session.query(*event_cols)
        # filter by scouting_team_number if it exists as a real column
        st_attr = getattr(Event, 'scouting_team_number', None)
        if isinstance(st_attr, InstrumentedAttribute):
            query = query.filter(st_attr == team_number)

        events_rows = query.all()
        for row in events_rows:
            # row is a KeyedTuple; access attributes by name when possible
            rowdict = {}
            for col in event_cols:
                col_name = col.key if hasattr(col, 'key') else None
                val = getattr(row, col_name) if col_name and hasattr(row, col_name) else None
                # if dates, isoformat
                if hasattr(val, 'isoformat'):
                    val = val.isoformat()
                rowdict[col_name or 'unknown'] = val
            events_data.append(rowdict)

        # Matches - column-only
        matches_rows = db.session.query(
            Match.id, Match.match_number, Match.match_type, Match.event_id, Match.red_alliance, Match.blue_alliance, Match.red_score, Match.blue_score, Match.winner
        ).filter(Match.scouting_team_number == team_number).all()
        matches_data = [
            {
                'id': row.id,
                'match_number': row.match_number,
                'match_type': row.match_type,
                'event_id': row.event_id,
                'red_alliance': row.red_alliance,
                'blue_alliance': row.blue_alliance,
                'red_score': row.red_score,
                'blue_score': row.blue_score,
                'winner': row.winner
            }
            for row in matches_rows
        ]

        # Scouting data - column-only
        # Use underlying JSON column and scout_name to avoid property access that triggers User lookups
        scouting_rows = db.session.query(
            ScoutingData.id, ScoutingData.team_id, ScoutingData.match_id, ScoutingData.data_json, ScoutingData.scout_name, ScoutingData.timestamp
        ).filter(ScoutingData.scouting_team_number == team_number).all()
        scouting_list = []
        for row in scouting_rows:
            # row may be a KeyedTuple or tuple
            data_json_val = getattr(row, 'data_json', None) if hasattr(row, 'data_json') else (row[3] if len(row) > 3 else None)
            scout_name_val = getattr(row, 'scout_name', None) if hasattr(row, 'scout_name') else (row[4] if len(row) > 4 else None)
            timestamp_val = getattr(row, 'timestamp', None) if hasattr(row, 'timestamp') else (row[5] if len(row) > 5 else None)
            # parse JSON safely
            parsed_data = None
            try:
                parsed_data = json.loads(data_json_val) if data_json_val else None
            except Exception:
                parsed_data = data_json_val

            scouting_list.append({
                'id': getattr(row, 'id', row[0]),
                'team_id': getattr(row, 'team_id', row[1]),
                'match_id': getattr(row, 'match_id', row[2]),
                'data': parsed_data,
                'scout_name': scout_name_val,
                'timestamp': timestamp_val.isoformat() if timestamp_val is not None and hasattr(timestamp_val, 'isoformat') else None
            })

        return jsonify({
            'success': True,
            'team_number': team_number,
            'teams': teams_data,
            'events': events_data,
            'matches': matches_data,
            'scouting_data': scouting_list
        })
    except Exception as e:
        # Log full traceback for debugging
        tb = traceback.format_exc()
        current_app.logger.error(f"Error in api_dump_all: {e}\n{tb}")
        # Return a helpful but concise error message for local debugging
        return jsonify({'error': 'Failed to dump data', 'details': str(e)}), 500