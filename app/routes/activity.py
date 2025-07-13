from flask import Blueprint, request, jsonify, current_app, render_template
from flask_login import current_user, login_required
from app import db
from app.models import ActivityLog, User
from sqlalchemy import desc
from datetime import datetime, timedelta
import json
from flask_paginate import Pagination, get_page_parameter

# Create blueprint
activity_bp = Blueprint('activity', __name__, url_prefix='/activity')

@activity_bp.route('/log_activity', methods=['POST'])
def log_activity():
    """API endpoint to log user activity"""
    try:
        print("Activity log endpoint called")
        print(f"Request headers: {request.headers}")
        print(f"Request method: {request.method}")
        print(f"Content type: {request.content_type}")
        
        # Debug output for the raw request data
        print(f"Raw request data: {request.get_data()}")
        
        data = request.json
        
        if not data or 'logs' not in data:
            print("Invalid request format: missing 'logs' field")
            return jsonify({'error': 'Invalid request format'}), 400
        
        logs = data['logs']
        print(f"Processing {len(logs)} activity log entries")
        
        for log_data in logs:
            # Get user info - handle cases where current_user might not be available
            try:
                user_id = current_user.id if current_user.is_authenticated else None
                username = current_user.username if current_user.is_authenticated else 'Anonymous'
            except Exception as e:
                print(f"Error accessing current_user: {e}")
                user_id = None
                username = 'Anonymous'
            
            # Create log entry
            log = ActivityLog(
                user_id=user_id,
                username=username,
                action_type=log_data.get('actionType'),
                page=log_data.get('page'),
                element_id=log_data.get('elementId'),
                element_type=log_data.get('elementType'),
                data=json.dumps(log_data.get('data')),
                ip_address=request.remote_addr,
                user_agent=log_data.get('userAgent') or request.user_agent.string
            )
            print(f"Logging action: {log_data.get('actionType')} by {username}")
            db.session.add(log)
        
        db.session.commit()
        print("Activity logs committed to database successfully")
        
        return jsonify({'status': 'success', 'logged_entries': len(logs)}), 200
    except Exception as e:
        current_app.logger.error(f"Error logging activity: {str(e)}")
        return jsonify({'error': str(e)}), 500

@activity_bp.route('/test', methods=['GET'])
def test_log():
    """Test endpoint to create a log entry"""
    try:
        # Create a test log entry
        log = ActivityLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            username=current_user.username if current_user.is_authenticated else 'Test User',
            action_type='test',
            page='/activity/test',
            element_id='test-button',
            element_type='BUTTON',
            data=json.dumps({"test": True, "timestamp": datetime.utcnow().isoformat()}),
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Test log entry created successfully",
            "log_id": log.id
        })
    except Exception as e:
        print(f"Error creating test log: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@activity_bp.route('/logs', methods=['GET'])
@login_required
def view_logs():
    """Admin interface to view activity logs"""
    # Check if user has admin role
    if not current_user.has_role('admin'):
        return "Access denied: Admin privileges required", 403
    
    # Get filter parameters
    username = request.args.get('username', '')
    action_type = request.args.get('action_type', '')
    page_filter = request.args.get('page', '')
    date_range = request.args.get('date_range', '')
    
    # Build query
    query = ActivityLog.query
    
    # Apply filters
    if username:
        query = query.filter(ActivityLog.username.ilike(f'%{username}%'))
    
    if action_type:
        query = query.filter(ActivityLog.action_type == action_type)
    
    if page_filter:
        query = query.filter(ActivityLog.page.ilike(f'%{page_filter}%'))
    
    if date_range:
        try:
            start_date_str, end_date_str = date_range.split(' to ')
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date = end_date + timedelta(days=1)  # Include the end date fully
            query = query.filter(ActivityLog.timestamp.between(start_date, end_date))
        except (ValueError, AttributeError):
            # Invalid date format, ignore filter
            pass
    
    # Order by timestamp descending (newest first)
    query = query.order_by(desc(ActivityLog.timestamp))
    
    # Pagination
    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 50  # Number of logs per page
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items
    
    return render_template('activity/logs.html', 
                          logs=logs, 
                          pagination=pagination)
