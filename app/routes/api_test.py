from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.routes.auth import admin_required
from app.utils.api_utils import get_teams_dual_api, get_matches_dual_api, get_event_details_dual_api, ApiError
from app.utils.tba_api_utils import TBAApiError, construct_tba_event_key
from app.models import Event, Team, Match
from app import db
from app.utils.theme_manager import ThemeManager
from app.utils.config_manager import get_current_game_config

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('api_test', __name__, url_prefix='/api_test')

@bp.route('/')
@admin_required
def index():
    """API testing interface"""
    return render_template('api_test/index.html', **get_theme_context())

@bp.route('/test_teams/<event_code>')
@admin_required
def test_teams(event_code):
    """Test dual API teams functionality"""
    try:
        teams = get_teams_dual_api(event_code)
        return jsonify({
            'success': True,
            'event_code': event_code,
            'teams_count': len(teams),
            'teams': teams[:5],  # Show first 5 teams as sample
            'message': f'Successfully retrieved {len(teams)} teams'
        })
    except (ApiError, TBAApiError) as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'event_code': event_code
        })

@bp.route('/test_matches/<event_code>')
@admin_required
def test_matches(event_code):
    """Test dual API matches functionality"""
    try:
        matches = get_matches_dual_api(event_code)
        return jsonify({
            'success': True,
            'event_code': event_code,
            'matches_count': len(matches),
            'matches': matches[:5],  # Show first 5 matches as sample
            'message': f'Successfully retrieved {len(matches)} matches'
        })
    except (ApiError, TBAApiError) as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'event_code': event_code
        })

@bp.route('/test_event/<event_code>')
@admin_required
def test_event(event_code):
    """Test dual API event details functionality"""
    try:
        event_details = get_event_details_dual_api(event_code)
        return jsonify({
            'success': True,
            'event_code': event_code,
            'event_details': event_details,
            'message': 'Successfully retrieved event details'
        })
    except (ApiError, TBAApiError) as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'event_code': event_code
        })

@bp.route('/test_api_status')
@admin_required
def test_api_status():
    """Test API configuration status"""
    game_config = get_current_game_config()
    
    # Check FIRST API settings
    first_api_settings = game_config.get('api_settings', {})
    first_api_configured = bool(first_api_settings.get('auth_token'))
    
    # Check TBA API settings
    tba_api_settings = game_config.get('tba_api_settings', {})
    tba_api_configured = bool(tba_api_settings.get('auth_key'))
    
    # Get preferred API source
    preferred_source = game_config.get('preferred_api_source', 'first')
    
    return jsonify({
        'preferred_api_source': preferred_source,
        'first_api_configured': first_api_configured,
        'tba_api_configured': tba_api_configured,
        'first_api_settings': {
            'username': first_api_settings.get('username', ''),
            'has_auth_token': bool(first_api_settings.get('auth_token')),
            'base_url': first_api_settings.get('base_url', 'https://frc-api.firstinspires.org')
        },
        'tba_api_settings': {
            'has_auth_key': bool(tba_api_settings.get('auth_key')),
            'base_url': tba_api_settings.get('base_url', 'https://www.thebluealliance.com/api/v3')
        }
    })

@bp.route('/quick_test', methods=['POST'])
@admin_required
def quick_test():
    """Quick test with a known event"""
    event_code = request.json.get('event_code', '2024cala')
    
    results = {
        'event_code': event_code,
        'teams': {'success': False, 'error': 'Not tested'},
        'matches': {'success': False, 'error': 'Not tested'},
        'event_details': {'success': False, 'error': 'Not tested'}
    }
    
    # Test teams
    try:
        teams = get_teams_dual_api(event_code)
        results['teams'] = {
            'success': True,
            'count': len(teams),
            'sample': teams[:3] if teams else []
        }
    except Exception as e:
        results['teams'] = {'success': False, 'error': str(e)}
    
    # Test matches
    try:
        matches = get_matches_dual_api(event_code)
        results['matches'] = {
            'success': True,
            'count': len(matches),
            'sample': matches[:3] if matches else []
        }
    except Exception as e:
        results['matches'] = {'success': False, 'error': str(e)}
    
    # Test event details
    try:
        event_details = get_event_details_dual_api(event_code)
        results['event_details'] = {
            'success': True,
            'data': event_details
        }
    except Exception as e:
        results['event_details'] = {'success': False, 'error': str(e)}
    
    return jsonify(results)
