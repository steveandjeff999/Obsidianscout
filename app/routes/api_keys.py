"""
API Key Management Routes
Handles creation, viewing, and management of API keys for team admins
"""
from flask import Blueprint, request, jsonify, current_app, render_template, abort
from flask_login import login_required, current_user
from datetime import datetime
import traceback

from app.api_models import (
    api_db, create_api_key, get_team_api_keys, count_team_api_keys, 
    deactivate_api_key, get_api_usage_stats, reactivate_api_key, delete_api_key_permanently
)
from app.models import Team, Event, Match, ScoutingData
from app import db
from app.routes.auth import admin_required

bp = Blueprint('api_keys', __name__, url_prefix='/api/keys')

def system_only():
    # Allow only requests with X-System-Internal header or from localhost
    internal_header = request.headers.get('X-System-Internal', '').lower() == 'true'
    is_localhost = request.remote_addr in ['127.0.0.1', '::1']
    if not (internal_header or is_localhost):
        abort(403)


@bp.route('/manage')
@login_required
@admin_required
def manage_api_keys():
    """API key management page"""
    return render_template('api_keys.html')


@bp.route('/', methods=['GET'])
@login_required
@admin_required
def list_api_keys():
    """List all API keys for the current user's team"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        api_keys = get_team_api_keys(team_number)
        keys_data = [key.to_dict(include_stats=False) for key in api_keys]
        
        return jsonify({
            'success': True,
            'api_keys': keys_data,
            'total_count': len(keys_data),
            'active_count': sum(1 for key in keys_data if key['is_active'])
        })
        
    except Exception as e:
        current_app.logger.error(f"Error listing API keys: {str(e)}")
        return jsonify({'error': 'Failed to retrieve API keys'}), 500


@bp.route('/', methods=['POST'])
@login_required
@admin_required
def create_new_api_key():
    """Create a new API key for the current user's team"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data or not data.get('name'):
            return jsonify({'error': 'API key name is required'}), 400
        
        name = data.get('name').strip()
        if len(name) < 3:
            return jsonify({'error': 'API key name must be at least 3 characters'}), 400
        
        description = data.get('description', '').strip()
        rate_limit = data.get('rate_limit_per_hour', 1000)
        expires_days = data.get('expires_days')
        
        # Validate rate limit
        if not isinstance(rate_limit, int) or rate_limit < 1 or rate_limit > 10000:
            return jsonify({'error': 'Rate limit must be between 1 and 10000 requests per hour'}), 400
        
        # Validate expiration
        if expires_days is not None:
            if not isinstance(expires_days, int) or expires_days < 1 or expires_days > 365:
                return jsonify({'error': 'Expiration must be between 1 and 365 days'}), 400
        
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        # Set default permissions for team access
        permissions = {
            'team_data_access': True,
            'scouting_data_read': True,
            'scouting_data_write': False,  # Can be enabled by superadmin
            'sync_operations': True,
            'analytics_access': True
        }
        
        # Override permissions if provided (only for superadmins)
        if current_user.has_role('superadmin') and data.get('permissions'):
            permissions.update(data.get('permissions'))
        
        # Create the API key
        api_key_data = create_api_key(
            name=name,
            team_number=team_number,
            created_by=current_user.username,
            description=description if description else None,
            permissions=permissions,
            rate_limit=rate_limit,
            expires_days=expires_days
        )
        
        return jsonify({
            'success': True,
            'message': 'API key created successfully',
            'api_key': api_key_data
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating API key: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'Failed to create API key'}), 500


@bp.route('/<int:api_key_id>', methods=['GET'])
@login_required
@admin_required
def get_api_key_details(api_key_id):
    """Get detailed information about a specific API key"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        # Get the API key
        api_keys = get_team_api_keys(team_number)
        api_key = next((key for key in api_keys if key.id == api_key_id), None)
        
        if not api_key:
            return jsonify({'error': 'API key not found'}), 404
        
        # Get usage statistics
        usage_stats = get_api_usage_stats(api_key_id, days=30)
        
        return jsonify({
            'success': True,
            'api_key': api_key.to_dict(include_stats=True),
            'usage_stats': usage_stats
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting API key details: {str(e)}")
        return jsonify({'error': 'Failed to retrieve API key details'}), 500


@bp.route('/<int:api_key_id>', methods=['PUT'])
@login_required
@admin_required
def update_api_key(api_key_id):
    """Update an existing API key"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Get the API key from the separate database
        session = api_db.get_session()
        try:
            from app.api_models import ApiKey
            api_key = session.query(ApiKey).filter_by(id=api_key_id, team_number=team_number).first()
            
            if not api_key:
                return jsonify({'error': 'API key not found'}), 404
            
            # Update allowed fields
            if 'name' in data:
                name = data['name'].strip()
                if len(name) < 3:
                    return jsonify({'error': 'API key name must be at least 3 characters'}), 400
                api_key.name = name
            
            if 'description' in data:
                api_key.description = data['description'].strip() if data['description'] else None
            
            if 'rate_limit_per_hour' in data:
                rate_limit = data['rate_limit_per_hour']
                if not isinstance(rate_limit, int) or rate_limit < 1 or rate_limit > 10000:
                    return jsonify({'error': 'Rate limit must be between 1 and 10000 requests per hour'}), 400
                api_key.rate_limit_per_hour = rate_limit
            
            if 'is_active' in data:
                api_key.is_active = bool(data['is_active'])
            
            # Only superadmins can update permissions
            if 'permissions' in data and current_user.has_role('superadmin'):
                api_key.permissions = data['permissions']
            
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'API key updated successfully',
                'api_key': api_key.to_dict(include_stats=False)
            })
            
        finally:
            api_db.close_session(session)
        
    except Exception as e:
        current_app.logger.error(f"Error updating API key: {str(e)}")
        return jsonify({'error': 'Failed to update API key'}), 500


@bp.route('/<int:api_key_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_api_key(api_key_id):
    """Deactivate (soft delete) an API key"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400

        # If caller provided ?permanent=1, delete permanently
        permanent = request.args.get('permanent', '0') in ['1', 'true', 'True']

        if permanent:
            success = delete_api_key_permanently(api_key_id, team_number)
            if not success:
                return jsonify({'error': 'API key not found'}), 404
            return jsonify({'success': True, 'message': 'API key permanently deleted'})

        success = deactivate_api_key(api_key_id, team_number)

        if not success:
            return jsonify({'error': 'API key not found'}), 404

        return jsonify({
            'success': True,
            'message': 'API key deactivated successfully'
        })
        
    except Exception as e:
        current_app.logger.error(f"Error deleting API key: {str(e)}")
        return jsonify({'error': 'Failed to delete API key'}), 500


@bp.route('/<int:api_key_id>/usage', methods=['GET'])
@login_required
@admin_required
def get_api_key_usage(api_key_id):
    """Get usage statistics for an API key"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        # Verify the API key belongs to the user's team
        api_keys = get_team_api_keys(team_number)
        api_key = next((key for key in api_keys if key.id == api_key_id), None)
        
        if not api_key:
            return jsonify({'error': 'API key not found'}), 404
        
        # Get query parameters
        days = request.args.get('days', 30, type=int)
        if days < 1 or days > 365:
            days = 30
        
        # Get usage statistics
        usage_stats = get_api_usage_stats(api_key_id, days=days)
        
        # Calculate summary statistics
        total_requests = len(usage_stats)
        successful_requests = sum(1 for stat in usage_stats if 200 <= stat['status_code'] < 300)
        failed_requests = total_requests - successful_requests
        
        # Group by date for daily statistics
        daily_stats = {}
        for stat in usage_stats:
            date_str = stat['timestamp'][:10]  # Extract date part
            if date_str not in daily_stats:
                daily_stats[date_str] = {'requests': 0, 'successful': 0, 'failed': 0}
            daily_stats[date_str]['requests'] += 1
            if 200 <= stat['status_code'] < 300:
                daily_stats[date_str]['successful'] += 1
            else:
                daily_stats[date_str]['failed'] += 1
        
        return jsonify({
            'success': True,
            'api_key_id': api_key_id,
            'period_days': days,
            'summary': {
                'total_requests': total_requests,
                'successful_requests': successful_requests,
                'failed_requests': failed_requests,
                'success_rate': (successful_requests / total_requests * 100) if total_requests > 0 else 0
            },
            'daily_stats': daily_stats,
            'usage_details': usage_stats
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting API key usage: {str(e)}")
        return jsonify({'error': 'Failed to retrieve usage statistics'}), 500


@bp.route('/test', methods=['GET'])
@login_required
@admin_required
def test_api_key_system():
    """Test endpoint to verify API key system is working"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400
        
        # Get team's API key count
        key_count = count_team_api_keys(team_number)
        
        return jsonify({
            'success': True,
            'message': 'API key system is working',
            'team_number': team_number,
            'api_key_count': key_count,
            'max_keys': 5,
            'user': current_user.username,
            'roles': current_user.get_role_names()
        })
        
    except Exception as e:
        current_app.logger.error(f"Error testing API key system: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': f'API key system test failed: {str(e)}'}), 500


@bp.route('/<int:api_key_id>/reactivate', methods=['POST'])
@login_required
@admin_required
def reactivate_key(api_key_id):
    """Reactivate a previously deactivated API key"""
    try:
        team_number = current_user.scouting_team_number
        if not team_number:
            return jsonify({'error': 'User not associated with a team'}), 400

        success = reactivate_api_key(api_key_id, team_number)

        if not success:
            return jsonify({'error': 'API key not found'}), 404

        return jsonify({'success': True, 'message': 'API key reactivated successfully'})
    except Exception as e:
        current_app.logger.error(f"Error reactivating API key: {str(e)}")
        return jsonify({'error': 'Failed to reactivate API key'}), 500


@bp.route('/all', methods=['GET'])
@login_required
@admin_required
def dump_all_team_data():
    """Dump all database data for the current admin's scouting team.

    Returns JSON with teams, events, matches, and scouting_data scoped to
    the current_user.scouting_team_number.
    """
    try:
        team_number = current_user.scouting_team_number
        if team_number is None:
            return jsonify({'error': 'User not associated with a scouting team'}), 400

        # Teams
        teams = Team.query.filter(Team.scouting_team_number == team_number).all()
        teams_data = []
        for t in teams:
            teams_data.append({
                'id': t.id,
                'team_number': t.team_number,
                'team_name': t.team_name,
                'location': t.location
            })

        # Events
        events = Event.query.filter(Event.scouting_team_number == team_number).all()
        events_data = []
        for e in events:
            events_data.append({
                'id': e.id,
                'name': e.name,
                'code': e.code,
                'location': getattr(e, 'location', None),
                'start_date': e.start_date.isoformat() if getattr(e, 'start_date', None) else None,
                'end_date': e.end_date.isoformat() if getattr(e, 'end_date', None) else None
            })

        # Matches
        matches = Match.query.filter(Match.scouting_team_number == team_number).all()
        matches_data = []
        for m in matches:
            matches_data.append({
                'id': m.id,
                'match_number': m.match_number,
                'match_type': m.match_type,
                'event_id': m.event_id,
                'red_alliance': m.red_alliance,
                'blue_alliance': m.blue_alliance,
                'red_score': m.red_score,
                'blue_score': m.blue_score,
                'winner': m.winner
            })

        # Scouting data
        scouting = ScoutingData.query.filter(ScoutingData.scouting_team_number == team_number).all()
        scouting_list = []
        for s in scouting:
            scouting_list.append({
                'id': s.id,
                'team_id': s.team_id,
                'match_id': s.match_id,
                'data': s.data,
                'scout': s.scout,
                'timestamp': s.timestamp.isoformat() if getattr(s, 'timestamp', None) else None
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
        current_app.logger.error(f"Error dumping team data: {e}")
        return jsonify({'error': 'Failed to dump team data'}), 500
