"""
API Key Management Routes
Handles creation, viewing, and management of API keys for team admins
"""
from flask import Blueprint, request, jsonify, current_app, render_template
from flask_login import login_required, current_user
from datetime import datetime
import traceback

from app.api_models import (
    api_db, create_api_key, get_team_api_keys, count_team_api_keys, 
    deactivate_api_key, get_api_usage_stats
)
from app.routes.auth import admin_required

bp = Blueprint('api_keys', __name__, url_prefix='/api/keys')


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
