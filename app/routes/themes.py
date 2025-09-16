from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, make_response
from flask_login import login_required, current_user
from app.routes.auth import admin_required
from app.utils.theme_manager import ThemeManager
import json
import time

bp = Blueprint('themes', __name__, url_prefix='/themes')

def get_theme_context():
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        team_number = getattr(current_user, 'scouting_team_number', None)
    
    theme_manager = ThemeManager(team_number=team_number)
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

@bp.route('/')
@login_required
def index():
    """Simple theme toggle between light and dark mode"""
    return render_template('themes/simple.html', **get_theme_context())

@bp.route('/toggle', methods=['POST'])
@login_required
def toggle_theme():
    """Toggle between light and dark theme"""
    team_number = getattr(current_user, 'scouting_team_number', None)
    if not team_number:
        if request.is_json:
            return jsonify({'success': False, 'message': 'No team assigned to user'}), 400
        flash('No team assigned to user', 'danger')
        return redirect(url_for('themes.index'))
    
    theme_manager = ThemeManager(team_number=team_number)
    
    # Toggle between light and dark
    current_theme_id = theme_manager.current_theme
    new_theme_id = 'dark' if current_theme_id == 'light' else 'light'
    
    if theme_manager.set_current_theme(new_theme_id):
        # Also save as team fallback preference
        theme_manager.save_team_theme_preference(new_theme_id, team_number)
        
        theme = theme_manager.get_current_theme()
        msg = f'Switched to {theme["name"]}'
        
        # Create response with cookie
        if request.is_json:
            response = make_response(jsonify({'success': True, 'message': msg, 'theme': new_theme_id}))
        else:
            flash(msg, 'success')
            response = make_response(redirect(url_for('themes.index')))
        
        # Set cookie for this team and device (expires in 1 year)
        cookie_name = f"theme_team_{team_number}"
        response.set_cookie(cookie_name, new_theme_id, max_age=365*24*60*60, httponly=True, samesite='Lax')
        
        return response
    else:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Failed to toggle theme'}), 400
        flash('Failed to toggle theme', 'danger')
        return redirect(url_for('themes.index'))

@bp.route('/apply/<theme_id>', methods=['POST'])
@login_required
def apply_theme(theme_id):
    """Apply a specific theme (light or dark)"""
    team_number = getattr(current_user, 'scouting_team_number', None)
    if not team_number:
        if request.is_json:
            return jsonify({'success': False, 'message': 'No team assigned to user'}), 400
        flash('No team assigned to user', 'danger')
        return redirect(url_for('themes.index'))
    
    # Only allow light or dark themes
    if theme_id not in ['light', 'dark']:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid theme'}), 400
        flash('Invalid theme', 'danger')
        return redirect(url_for('themes.index'))
    
    theme_manager = ThemeManager(team_number=team_number)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes['application/json'] > 0
    
    if theme_manager.set_current_theme(theme_id):
        # Also save as team fallback preference
        theme_manager.save_team_theme_preference(theme_id, team_number)
        
        theme = theme_manager.get_current_theme()
        msg = f'The theme "{theme["name"]}" has been applied successfully for your device!'
        
        # Create response with cookie
        if is_ajax:
            response = make_response(jsonify({'success': True, 'message': msg}))
        else:
            flash(msg, 'success')
            response = make_response(redirect(url_for('themes.index')))
        
        # Set cookie for this team and device (expires in 1 year)
        cookie_name = f"theme_team_{team_number}"
        response.set_cookie(cookie_name, theme_id, max_age=365*24*60*60, httponly=True, samesite='Lax')
        
        return response
    else:
        if is_ajax:
            return jsonify({'success': False, 'message': 'Failed to apply theme. Theme not found.'}), 400
        flash('Failed to apply theme. Theme not found.', 'danger')
        return redirect(url_for('themes.index'))

@bp.route('/api/current-theme')
def get_current_theme():
    """API endpoint to get current theme CSS variables"""
    team_number = None
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        team_number = getattr(current_user, 'scouting_team_number', None)
    
    theme_manager = ThemeManager(team_number=team_number)
    theme = theme_manager.get_current_theme()
    
    return jsonify({
        'theme_id': theme_manager.current_theme,
        'name': theme.get('name', ''),
        'css_variables': theme_manager.get_theme_css_variables()
    }) 