"""
Setup Wizard Routes for ObsidianScout
Handles first-time setup and tutorial flows for new installations
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, Role, Team, Event
from app.utils.database_init import initialize_database, check_database_health
from app.utils.config_manager import get_current_game_config, get_current_pit_config
from app.utils.theme_manager import ThemeManager
import os
import json

def get_theme_context():
    theme_manager = ThemeManager()
    return {
        'themes': theme_manager.get_available_themes(),
        'current_theme_id': theme_manager.current_theme
    }

bp = Blueprint('setup', __name__, url_prefix='/setup')

@bp.route('/')
def index():
    """Main setup wizard landing page"""
    # Check database health and gather detailed info
    try:
        from app.models import User, Role
        user_count = User.query.count()
        role_count = Role.query.count()
        admin_user = User.query.filter_by(username='admin').first()
        
        health = {
            'database_exists': True,
            'tables_created': True,
            'has_users': user_count > 0,
            'user_count': user_count,
            'has_admin': admin_user is not None,
            'configs_exist': (
                os.path.exists('config/game_config.json') and 
                os.path.exists('config/pit_config.json')
            )
        }
    except Exception as e:
        health = {
            'database_exists': False,
            'tables_created': False,
            'has_users': False,
            'user_count': 0,
            'has_admin': False,
            'configs_exist': False
        }
    
    # Check if this is first run
    is_first_run = not health['has_users']
    
    # Check if setup is completed
    setup_completed = session.get('setup_completed', False)
    
    return render_template('setup/index.html', 
                         is_first_run=is_first_run,
                         setup_completed=setup_completed,
                         health=health,
                         **get_theme_context())

@bp.route('/tutorial')
def tutorial():
    """Interactive tutorial for new users"""
    return render_template('setup/tutorial.html', **get_theme_context())

@bp.route('/first-run', methods=['GET', 'POST'])
def first_run():
    """First-time setup wizard for new installations"""
    if request.method == 'POST':
        step = request.form.get('step', '1')
        
        if step == '1':
            # Step 1: Basic setup info
            team_number = request.form.get('team_number')
            team_name = request.form.get('team_name')
            admin_username = request.form.get('admin_username', 'admin')
            admin_password = request.form.get('admin_password', 'password')
            
            # Store in session for next step
            session['setup_data'] = {
                'team_number': team_number,
                'team_name': team_name,
                'admin_username': admin_username,
                'admin_password': admin_password
            }
            
            return redirect(url_for('setup.first_run', step=2))
            
        elif step == '2':
            # Step 2: Create admin user and team
            setup_data = session.get('setup_data', {})
            
            try:
                # Initialize database
                initialize_database()
                
                # Create admin user
                admin_role = Role.query.filter_by(name='admin').first()
                if not admin_role:
                    admin_role = Role(name='admin', description='Full system access')
                    db.session.add(admin_role)
                    db.session.commit()
                
                admin_user = User(
                    username=setup_data['admin_username'],
                    scouting_team_number=int(setup_data['team_number'])
                )
                admin_user.set_password(setup_data['admin_password'])
                admin_user.roles.append(admin_role)
                
                db.session.add(admin_user)
                
                # Create team record
                team = Team.query.filter_by(team_number=int(setup_data['team_number'])).first()
                if not team:
                    team = Team(
                        team_number=int(setup_data['team_number']),
                        team_name=setup_data['team_name']
                    )
                    db.session.add(team)
                
                db.session.commit()
                
                session['setup_completed'] = True
                flash('Setup completed successfully!', 'success')
                return redirect(url_for('setup.complete'))
                
            except Exception as e:
                flash(f'Setup failed: {str(e)}', 'error')
                return redirect(url_for('setup.first_run'))
    
    # GET request - show setup form
    step = request.args.get('step', '1')
    return render_template('setup/first_run.html', 
                         step=int(step),
                         setup_data=session.get('setup_data', {}),
                         **get_theme_context())

@bp.route('/complete')
def complete():
    """Setup completion page"""
    if not session.get('setup_completed'):
        return redirect(url_for('setup.index'))
    
    return render_template('setup/complete.html', **get_theme_context())

@bp.route('/system-check')
@login_required
def system_check():
    """System health and configuration check"""
    if not current_user.has_role('admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('main.index'))
    
    # Perform comprehensive system check
    try:
        from app.models import User, Role
        user_count = User.query.count()
        role_count = Role.query.count()
        admin_user = User.query.filter_by(username='admin').first()
        
        health = {
            'database_exists': True,
            'tables_created': True,
            'has_users': user_count > 0,
            'user_count': user_count,
            'has_admin': admin_user is not None,
            'configs_exist': (
                os.path.exists('config/game_config.json') and 
                os.path.exists('config/pit_config.json')
            )
        }
    except Exception as e:
        health = {
            'database_exists': False,
            'tables_created': False,
            'has_users': False,
            'user_count': 0,
            'has_admin': False,
            'configs_exist': False
        }
    
    # Check configuration files
    config_status = {
        'game_config': os.path.exists('config/game_config.json'),
        'pit_config': os.path.exists('config/pit_config.json'),
        'theme_config': os.path.exists('config/theme_config.json'),
        'sync_config': os.path.exists('config/sync_config.json')
    }
    
    # Check for required directories
    directories = ['instance', 'config', 'uploads', 'instance/chat', 'instance/configs']
    directory_status = {dir_name: os.path.exists(dir_name) for dir_name in directories}
    
    # Count users by role
    role_counts = {}
    try:
        for role in Role.query.all():
            role_counts[role.name] = len(role.users)
    except Exception:
        role_counts = {}
    
    return render_template('setup/system_check.html',
                         health=health,
                         config_status=config_status,
                         directory_status=directory_status,
                         role_counts=role_counts,
                         **get_theme_context())

@bp.route('/features')
def features():
    """Feature overview and quick start guide"""
    return render_template('setup/features.html', **get_theme_context())

@bp.route('/api/check-database')
def api_check_database():
    """API endpoint to check database status"""
    try:
        from app.models import User, Role
        user_count = User.query.count()
        role_count = Role.query.count()
        admin_user = User.query.filter_by(username='admin').first()
        
        health = {
            'database_exists': True,
            'tables_created': True,
            'has_users': user_count > 0,
            'user_count': user_count,
            'has_admin': admin_user is not None,
            'configs_exist': (
                os.path.exists('config/game_config.json') and 
                os.path.exists('config/pit_config.json')
            )
        }
    except Exception as e:
        health = {
            'database_exists': False,
            'tables_created': False,
            'has_users': False,
            'user_count': 0,
            'has_admin': False,
            'configs_exist': False
        }
    
    return jsonify(health)

@bp.route('/api/check-team/<int:team_number>')
def api_check_team(team_number):
    """Check if a team number is already in use"""
    team = Team.query.filter_by(team_number=team_number).first()
    user = User.query.filter_by(scouting_team_number=team_number).first()
    
    return jsonify({
        'team_exists': team is not None,
        'users_exist': user is not None,
        'available': team is None and user is None
    })

@bp.route('/initialize-sample-data', methods=['POST'])
@login_required
def initialize_sample_data():
    """Initialize sample data for testing (admin only)"""
    if not current_user.has_role('admin'):
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        from app.utils.database_init import seed_sample_data
        seed_sample_data()
        
        return jsonify({
            'success': True,
            'message': 'Sample data initialized successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/wizard')
@login_required
def setup_wizard():
    """Windows-style setup wizard for team configuration"""
    return render_template('setup/wizard.html', **get_theme_context())

@bp.route('/wizard/step/<int:step>')
@login_required
def wizard_step(step):
    """Individual setup wizard steps"""
    if step < 1 or step > 5:
        return redirect(url_for('setup.setup_wizard'))
    
    # Get current configuration status
    try:
        health = {
            'database': bool(User.query.first()),
            'users': User.query.count(),
            'teams': Team.query.count(),
            'events': Event.query.count(),
            'roles': Role.query.count()
        }
    except:
        health = {
            'database': False,
            'users': 0,
            'teams': 0,
            'events': 0,
            'roles': 0
        }
    
    return render_template(f'setup/wizard_step_{step}.html', 
                         step=step, 
                         health=health,
                         **get_theme_context())

@bp.route('/wizard/api/save-step', methods=['POST'])
@login_required
def save_wizard_step():
    """Save wizard step data"""
    try:
        data = request.get_json()
        step = data.get('step')
        form_data = data.get('data', {})
        
        # Store step data in session
        if 'wizard_data' not in session:
            session['wizard_data'] = {}
        
        session['wizard_data'][f'step_{step}'] = form_data
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': f'Step {step} data saved successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@bp.route('/wizard/api/complete', methods=['POST'])
@login_required
def complete_wizard():
    """Complete the setup wizard and apply all settings"""
    try:
        wizard_data = session.get('wizard_data', {})
        
        # Apply team settings from Step 1
        step1_data = wizard_data.get('step_1', {})
        if step1_data:
            # Update team configuration
            # This would implement actual team config updates
            pass
        
        # Apply user settings from Step 2
        step2_data = wizard_data.get('step_2', {})
        if step2_data:
            # Create/update users
            # This would implement user management
            pass
        
        # Apply event settings from Step 3
        step3_data = wizard_data.get('step_3', {})
        if step3_data:
            # Configure events
            # This would implement event setup
            pass
        
        # Apply theme settings from Step 4
        step4_data = wizard_data.get('step_4', {})
        if step4_data:
            # Apply theme
            # This would implement theme application
            pass
        
        # Mark wizard as completed
        session['wizard_completed'] = True
        session.modified = True
        
        return jsonify({
            'success': True,
            'message': 'Setup wizard completed successfully!',
            'redirect': url_for('main.index')
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
