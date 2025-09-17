"""
API Authentication Middleware
Handles authentication and authorization for API requests using API keys
"""
from functools import wraps
from flask import request, jsonify, current_app, g
from datetime import datetime
import time
import hashlib

from app.api_models import (
    get_api_key_by_hash, record_api_usage, check_rate_limit, ApiKey
)


def extract_api_key_from_request():
    """Extract API key from request headers or query parameters"""
    # Try Authorization header first (preferred)
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip()
    
    # Try X-API-Key header
    api_key = request.headers.get('X-API-Key', '').strip()
    if api_key:
        return api_key
    
    # Try query parameter (less secure, for simple GET requests only)
    if request.method == 'GET':
        api_key = request.args.get('api_key', '').strip()
        if api_key:
            return api_key
    
    return None


def authenticate_api_key(api_key):
    """Authenticate an API key and return the key record if valid"""
    if not api_key:
        return None, "API key is required"
    
    # Validate format
    if not api_key.startswith('sk_live_') or len(api_key) != 40:
        return None, "Invalid API key format"
    
    try:
        # Hash the provided key to match against stored hash
        key_hash = ApiKey.hash_key(api_key)
        
        # Look up the key in the database
        session = None
        try:
            from app.api_models import api_db
            session = api_db.get_session()
            api_key_record = session.query(ApiKey).filter_by(key_hash=key_hash, is_active=True).first()
            
            if not api_key_record:
                return None, "Invalid API key"
            
            # Check if expired
            if api_key_record.expires_at and api_key_record.expires_at < datetime.utcnow():
                return None, "API key has expired"
            
            return api_key_record, None
            
        finally:
            if session:
                api_db.close_session(session)
                
    except Exception as e:
        current_app.logger.error(f"Error authenticating API key: {str(e)}")
        return None, "Authentication error"


def check_api_permissions(api_key_record, required_permission):
    """Check if an API key has the required permission"""
    permissions = api_key_record.permissions or {}
    
    # Check specific permission
    if required_permission and not permissions.get(required_permission, False):
        return False, f"API key lacks required permission: {required_permission}"
    
    return True, None


def api_key_required(permission=None):
    """Decorator to require valid API key authentication for API endpoints"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            
            # Extract API key from request
            api_key = extract_api_key_from_request()
            
            # Authenticate the API key
            api_key_record, auth_error = authenticate_api_key(api_key)
            if auth_error:
                # Record failed usage
                if api_key:
                    try:
                        record_api_usage(
                            api_key_id=0,  # Unknown key
                            endpoint=request.path,
                            method=request.method,
                            status_code=401,
                            ip_address=request.remote_addr,
                            user_agent=request.headers.get('User-Agent'),
                            request_size=len(request.get_data()),
                            response_time_ms=(time.time() - start_time) * 1000,
                            error_message=auth_error
                        )
                    except:
                        pass  # Don't let logging errors break the response
                
                return jsonify({
                    'error': auth_error,
                    'code': 'INVALID_API_KEY'
                }), 401
            
            # Check permissions
            if permission:
                has_permission, perm_error = check_api_permissions(api_key_record, permission)
                if not has_permission:
                    # Record unauthorized usage
                    try:
                        record_api_usage(
                            api_key_id=api_key_record.id,
                            endpoint=request.path,
                            method=request.method,
                            status_code=403,
                            ip_address=request.remote_addr,
                            user_agent=request.headers.get('User-Agent'),
                            request_size=len(request.get_data()),
                            response_time_ms=(time.time() - start_time) * 1000,
                            error_message=perm_error
                        )
                    except:
                        pass
                    
                    return jsonify({
                        'error': perm_error,
                        'code': 'INSUFFICIENT_PERMISSIONS'
                    }), 403
            
            # Check rate limits
            within_limit, current_count = check_rate_limit(
                api_key_record.id, 
                api_key_record.rate_limit_per_hour
            )
            
            if not within_limit:
                # Record rate limited usage
                try:
                    record_api_usage(
                        api_key_id=api_key_record.id,
                        endpoint=request.path,
                        method=request.method,
                        status_code=429,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent'),
                        request_size=len(request.get_data()),
                        response_time_ms=(time.time() - start_time) * 1000,
                        error_message=f"Rate limit exceeded: {current_count}/{api_key_record.rate_limit_per_hour}"
                    )
                except:
                    pass
                
                return jsonify({
                    'error': f'Rate limit exceeded. Current: {current_count}/{api_key_record.rate_limit_per_hour} requests per hour',
                    'code': 'RATE_LIMIT_EXCEEDED',
                    'retry_after': 3600  # Retry after 1 hour
                }), 429
            
            # Store API key info in Flask g for use in the endpoint
            g.api_key = api_key_record
            g.api_team_number = api_key_record.team_number
            g.api_permissions = api_key_record.permissions
            g.api_request_start_time = start_time
            
            try:
                # Call the actual endpoint function
                response = f(*args, **kwargs)
                
                # Record successful usage
                status_code = 200
                response_size = 0
                
                # Try to extract status code and size from response
                if hasattr(response, 'status_code'):
                    status_code = response.status_code
                if hasattr(response, 'content_length') and response.content_length:
                    response_size = response.content_length
                elif hasattr(response, 'data'):
                    response_size = len(response.data) if response.data else 0
                
                try:
                    record_api_usage(
                        api_key_id=api_key_record.id,
                        endpoint=request.path,
                        method=request.method,
                        status_code=status_code,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent'),
                        request_size=len(request.get_data()),
                        response_size=response_size,
                        response_time_ms=(time.time() - start_time) * 1000
                    )
                except Exception as e:
                    current_app.logger.error(f"Error recording API usage: {str(e)}")
                
                return response
                
            except Exception as e:
                # Record failed usage due to endpoint error
                try:
                    record_api_usage(
                        api_key_id=api_key_record.id,
                        endpoint=request.path,
                        method=request.method,
                        status_code=500,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent'),
                        request_size=len(request.get_data()),
                        response_time_ms=(time.time() - start_time) * 1000,
                        error_message=str(e)
                    )
                except:
                    pass
                
                # Re-raise the original exception
                raise
        
        return decorated_function
    return decorator


def team_data_access_required(f):
    """Decorator requiring team_data_access permission"""
    return api_key_required('team_data_access')(f)


def scouting_data_read_required(f):
    """Decorator requiring scouting_data_read permission"""
    return api_key_required('scouting_data_read')(f)


def scouting_data_write_required(f):
    """Decorator requiring scouting_data_write permission"""
    return api_key_required('scouting_data_write')(f)


def sync_operations_required(f):
    """Decorator requiring sync_operations permission"""
    return api_key_required('sync_operations')(f)


def analytics_access_required(f):
    """Decorator requiring analytics_access permission"""
    return api_key_required('analytics_access')(f)


def get_current_api_key():
    """Get the current API key record from Flask g"""
    return getattr(g, 'api_key', None)


def get_current_api_team():
    """Get the current API key's team number from Flask g"""
    return getattr(g, 'api_team_number', None)


def get_current_api_permissions():
    """Get the current API key's permissions from Flask g"""
    return getattr(g, 'api_permissions', {})


def has_api_permission(permission):
    """Check if the current API key has a specific permission"""
    permissions = get_current_api_permissions()
    return permissions.get(permission, False)
