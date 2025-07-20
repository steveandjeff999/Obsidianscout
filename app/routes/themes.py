from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required
from app.routes.auth import admin_required
from app.utils.theme_manager import ThemeManager
import json
import time

bp = Blueprint('themes', __name__, url_prefix='/themes')

@bp.route('/')
@login_required
@admin_required
def index():
    """Theme management dashboard"""
    theme_manager = ThemeManager()
    available_themes = theme_manager.get_available_themes()
    current_theme = theme_manager.get_current_theme()
    
    return render_template('themes/index.html', 
                          themes=available_themes,
                          current_theme=current_theme,
                          current_theme_id=theme_manager.current_theme)

@bp.route('/preview/<theme_id>')
@login_required
@admin_required
def preview_theme(theme_id):
    """Preview a specific theme"""
    theme_manager = ThemeManager()
    available_themes = theme_manager.get_available_themes()
    
    if theme_id not in available_themes:
        flash('Theme not found', 'danger')
        return redirect(url_for('themes.index'))
    
    theme_data = available_themes[theme_id]
    theme_data['id'] = theme_id
    
    return render_template('themes/preview.html', 
                          theme=theme_data,
                          all_themes=available_themes)

@bp.route('/apply/<theme_id>', methods=['POST'])
@login_required
@admin_required
def apply_theme(theme_id):
    """Apply a theme"""
    theme_manager = ThemeManager()
    
    if theme_manager.set_current_theme(theme_id):
        flash(f'The theme "{theme_manager.get_current_theme()["name"]}" has been applied successfully!', 'success')
    else:
        flash('Failed to apply theme. Theme not found.', 'danger')
    
    return redirect(url_for('themes.index'))

@bp.route('/edit/<theme_id>')
@login_required
@admin_required
def edit_theme(theme_id):
    """Edit a custom theme"""
    theme_manager = ThemeManager()
    available_themes = theme_manager.get_available_themes()
    
    if theme_id not in available_themes:
        flash('Theme not found', 'danger')
        return redirect(url_for('themes.index'))
    
    theme_data = available_themes[theme_id]
    theme_data['id'] = theme_id
    is_custom = theme_id in theme_manager.custom_themes
    
    return render_template('themes/edit.html', 
                          theme=theme_data,
                          is_custom=is_custom)

@bp.route('/edit/<theme_id>', methods=['POST'])
@login_required
@admin_required
def save_theme(theme_id):
    """Save theme changes"""
    theme_manager = ThemeManager()
    
    try:
        # Get form data
        theme_data = {
            'name': request.form.get('name', ''),
            'description': request.form.get('description', ''),
            'colors': {},
            'typography': {},
            'ui': {}
        }
        
        # Process color inputs
        for key in ['primary', 'primary-light', 'primary-dark', 'secondary', 'success', 
                   'danger', 'warning', 'info', 'light', 'dark', 'red-alliance', 
                   'red-alliance-bg', 'blue-alliance', 'blue-alliance-bg', 'auto-color', 
                   'teleop-color', 'endgame-color', 'navbar-bg', 'card-bg', 'card-border', 
                   'card-header', 'text-main', 'text-muted', 'background']:
            value = request.form.get(f'color_{key}', '')
            if value:
                theme_data['colors'][key] = value
        
        # Process typography inputs
        for key in ['font-family-base', 'font-family-headings']:
            value = request.form.get(f'typography_{key}', '')
            if value:
                theme_data['typography'][key] = value
        
        # Process UI inputs
        for key in ['border-radius', 'transition-speed', 'card-shadow', 'card-shadow-hover']:
            value = request.form.get(f'ui_{key}', '')
            if value:
                theme_data['ui'][key] = value
        
        # Validate required fields
        if not theme_data['name']:
            flash('Theme name is required', 'danger')
            return redirect(url_for('themes.edit_theme', theme_id=theme_id))
        
        # Save theme
        if theme_id in theme_manager.custom_themes:
            success = theme_manager.update_custom_theme(theme_id, theme_data)
        else:
            # Create new custom theme based on existing one
            new_theme_id = f"custom_{theme_id}_{int(time.time())}"
            success = theme_manager.create_custom_theme(new_theme_id, theme_data)
            if success:
                theme_id = new_theme_id
        
        if success:
            flash('Theme saved successfully!', 'success')
            return redirect(url_for('themes.edit_theme', theme_id=theme_id))
        else:
            flash('Failed to save theme', 'danger')
            
    except Exception as e:
        current_app.logger.error(f"Error saving theme: {e}")
        flash('An error occurred while saving the theme', 'danger')
    
    return redirect(url_for('themes.edit_theme', theme_id=theme_id))

@bp.route('/create')
@login_required
@admin_required
def create_theme():
    """Create a new custom theme"""
    theme_manager = ThemeManager()
    available_themes = theme_manager.get_available_themes()
    
    return render_template('themes/create.html', 
                          base_themes=available_themes)

@bp.route('/create', methods=['POST'])
@login_required
@admin_required
def save_new_theme():
    """Save a new custom theme"""
    theme_manager = ThemeManager()
    
    try:
        theme_id = request.form.get('theme_id', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        base_theme_id = request.form.get('base_theme', 'default')
        
        # Validate inputs
        if not theme_id or not name:
            flash('Theme ID and name are required', 'danger')
            return redirect(url_for('themes.create_theme'))
        
        # Check if theme ID already exists
        available_themes = theme_manager.get_available_themes()
        if theme_id in available_themes:
            flash('Theme ID already exists. Please choose a different ID.', 'danger')
            return redirect(url_for('themes.create_theme'))
        
        # Get base theme data
        if base_theme_id in available_themes:
            base_theme = available_themes[base_theme_id].copy()
        else:
            base_theme = available_themes['default'].copy()
        
        # Update with new data
        base_theme['name'] = name
        base_theme['description'] = description
        
        # Process color inputs
        for key in ['primary', 'primary-light', 'primary-dark', 'secondary', 'success', 
                   'danger', 'warning', 'info', 'light', 'dark', 'red-alliance', 
                   'red-alliance-bg', 'blue-alliance', 'blue-alliance-bg', 'auto-color', 
                   'teleop-color', 'endgame-color', 'navbar-bg', 'card-bg', 'card-border', 
                   'card-header', 'text-main', 'text-muted', 'background']:
            value = request.form.get(f'color_{key}', '')
            if value:
                base_theme['colors'][key] = value
        
        # Process typography inputs
        for key in ['font-family-base', 'font-family-headings']:
            value = request.form.get(f'typography_{key}', '')
            if value:
                base_theme['typography'][key] = value
        
        # Process UI inputs
        for key in ['border-radius', 'transition-speed', 'card-shadow', 'card-shadow-hover']:
            value = request.form.get(f'ui_{key}', '')
            if value:
                base_theme['ui'][key] = value
        
        # Create the theme
        if theme_manager.create_custom_theme(theme_id, base_theme):
            flash(f'Custom theme "{name}" created successfully!', 'success')
            return redirect(url_for('themes.edit_theme', theme_id=theme_id))
        else:
            flash('Failed to create theme', 'danger')
            
    except Exception as e:
        current_app.logger.error(f"Error creating theme: {e}")
        flash('An error occurred while creating the theme', 'danger')
    
    return redirect(url_for('themes.create_theme'))

@bp.route('/duplicate/<theme_id>', methods=['POST'])
@login_required
@admin_required
def duplicate_theme(theme_id):
    """Duplicate an existing theme"""
    theme_manager = ThemeManager()
    
    try:
        new_theme_id = request.form.get('new_theme_id', '').strip()
        new_name = request.form.get('new_name', '').strip()
        new_description = request.form.get('new_description', '').strip()
        
        # Validate inputs
        if not new_theme_id or not new_name:
            flash('New theme ID and name are required', 'danger')
            return redirect(url_for('themes.index'))
        
        # Check if new theme ID already exists
        available_themes = theme_manager.get_available_themes()
        if new_theme_id in available_themes:
            flash('Theme ID already exists. Please choose a different ID.', 'danger')
            return redirect(url_for('themes.index'))
        
        # Duplicate the theme
        if theme_manager.duplicate_theme(theme_id, new_theme_id, new_name, new_description):
            flash(f'Theme "{new_name}" created successfully!', 'success')
        else:
            flash('Failed to duplicate theme', 'danger')
            
    except Exception as e:
        current_app.logger.error(f"Error duplicating theme: {e}")
        flash('An error occurred while duplicating the theme', 'danger')
    
    return redirect(url_for('themes.index'))

@bp.route('/delete/<theme_id>', methods=['POST'])
@login_required
@admin_required
def delete_theme(theme_id):
    """Delete a custom theme"""
    theme_manager = ThemeManager()
    
    # Only allow deletion of custom themes
    if theme_id in theme_manager.custom_themes:
        theme_name = theme_manager.custom_themes[theme_id]['name']
        if theme_manager.delete_custom_theme(theme_id):
            flash(f'Theme "{theme_name}" deleted successfully!', 'success')
        else:
            flash('Failed to delete theme', 'danger')
    else:
        flash('Cannot delete built-in themes', 'danger')
    
    return redirect(url_for('themes.index'))

@bp.route('/api/current-theme')
def get_current_theme():
    """API endpoint to get current theme CSS variables"""
    theme_manager = ThemeManager()
    theme = theme_manager.get_current_theme()
    
    return jsonify({
        'theme_id': theme_manager.current_theme,
        'name': theme.get('name', ''),
        'css_variables': theme_manager.get_theme_css_variables()
    })

@bp.route('/api/preview/<theme_id>')
def preview_theme_api(theme_id):
    """API endpoint to preview theme CSS variables"""
    theme_manager = ThemeManager()
    available_themes = theme_manager.get_available_themes()
    
    if theme_id not in available_themes:
        return jsonify({'error': 'Theme not found'}), 404
    
    # Temporarily set the theme for preview
    original_theme = theme_manager.current_theme
    theme_manager.current_theme = theme_id
    
    theme = theme_manager.get_current_theme()
    css_variables = theme_manager.get_theme_css_variables()
    
    # Restore original theme
    theme_manager.current_theme = original_theme
    
    return jsonify({
        'theme_id': theme_id,
        'name': theme.get('name', ''),
        'css_variables': css_variables
    }) 